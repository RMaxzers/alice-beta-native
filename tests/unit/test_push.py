"""Push transport queue and HTTP API tests use fabricated RFC 8291 subscriptions."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from apps.api.db import connect, migrate
from services.tasks.push import PushService
from services.tasks.store import TaskError
from services.tasks.reminders import ReminderService
from packages.schemas.models import TaskIn


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


@pytest.fixture
def pushdb(tmp_path):
    con = connect(tmp_path / 'push.db')
    migrate(con)
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    path = tmp_path / 'vapid.pem'
    path.write_bytes(pem)
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    config = SimpleNamespace(alice_push_enabled=True, alice_push_private_key=path,
        alice_push_public_key=b64(pub), alice_push_subject='mailto:owner@example.com')
    sent = []
    service = PushService(con, config, sender=lambda sub, payload: sent.append((sub, payload)) or 201)
    yield con, service, sent, config
    con.close()


def subscription(endpoint='https://fcm.googleapis.com/fcm/send/test-endpoint', **kw):
    p = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {'endpoint': endpoint, 'expirationTime': None, 'keys': {'p256dh': b64(p), 'auth': b64(b'a' * 16)}, **kw}


def task(con, owner='ana'):
    from services.tasks.store import TaskStore
    return TaskStore(con, 'America/Santiago').create(owner, TaskIn(title='private task', due_date='2026-10-05', due_time='09:00'), origin='user', actor=owner)['task']


def test_push_optin_encrypted_generic_payload_and_stale_generation(pushdb):
    con, push, sent, _ = pushdb
    t = task(con)
    push.subscribe('ana', subscription(device_label='Laptop'))
    worker = ReminderService(con, True, push)
    now = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
    worker.tick(now)
    assert push.tick(now) == 1
    payload = sent[0][1]
    assert payload['body'] == 'Tienes un recordatorio pendiente'
    assert payload['task_id'] == t['task_id'] and payload['url'].endswith(f"task={t['task_id']}&reminder=1")
    assert 'private task' not in str(payload)
    assert push.tick(now) == 0


def test_push_subscription_isolation_rotation_and_cleanup(pushdb):
    con, push, _, _ = pushdb
    sub = subscription()
    push.subscribe('ana', sub)
    assert len(push.list('ana')['items']) == 1
    # DOMHighResTimeStamp is not necessarily epoch-based. Keep it and rely on 404/410.
    relative_expiry = subscription(endpoint='https://fcm.googleapis.com/fcm/send/relative', expirationTime=123456.7)
    push.subscribe('ana', relative_expiry)
    relative = next(item for item in push.list('ana')['items'] if item['endpoint'] == relative_expiry['endpoint'])
    assert relative['expirationTime'] is None
    with pytest.raises(TaskError) as exc:
        push.subscribe('beto', sub)
    assert exc.value.status == 409
    assert push.list('beto')['items'] == []
    with pytest.raises(TaskError) as exc:
        push.unsubscribe('beto', sub['endpoint'])
    assert exc.value.status == 404
    pushdb[0].execute('UPDATE push_subscriptions SET expiration_ms=?', (datetime.now(timezone.utc).timestamp()*1000-1,))
    assert push.tick() == 0 and push.list('ana')['items'] == []
    with pytest.raises(TaskError) as exc:
        push.subscribe('ana', subscription(endpoint='http://127.0.0.1:8000/steal'))
    assert exc.value.status == 422


def test_push_bad_vapid_key_is_disabled(pushdb):
    _, _, _, config = pushdb
    config.alice_push_public_key = b64(b'\x04' + b'x' * 64)
    service = PushService(pushdb[0], config)
    assert not service.config()['enabled'] and 'VAPID' in service.config()['reason']


def test_push_retry_backoff_expiry_and_gone_subscription(pushdb):
    con, _, _, config = pushdb
    errors = []
    def sender(sub, payload):
        errors.append(1)
        return 503 if len(errors) == 1 else 410
    push = PushService(con, config, sender)
    t = task(con)
    push.subscribe('ana', subscription())
    worker = ReminderService(con, True, push)
    now = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
    worker.tick(now)
    assert push.tick(now) == 1
    assert push.tick(now + timedelta(seconds=59)) == 0
    assert push.tick(now + timedelta(minutes=1)) == 1
    assert len(errors) == 2 and push.list('ana')['items'] == []
    assert con.execute('SELECT COUNT(*) FROM push_deliveries').fetchone()[0] == 0  # cascades after provider 410


def test_api_auth_csrf_and_user_scope(api, state):
    from tests.security.test_api_security import as_user
    assert api.c.get('/api/push/config').status_code == 200
    t = api.c.post('/api/tasks', json={'title': 'Reminder', 'due_date': '2026-10-05', 'due_time': '09:00',
                                      'recurrence': {'freq': 'daily', 'until': '2026-10-06'}}, headers=api.h()).json()['task']
    assert t['series_id'] and api.c.get('/api/tasks/' + t['task_id']).status_code == 200
    assert api.c.post('/api/series/' + t['series_id'] + '/stop').status_code == 403
    assert api.c.get('/api/summary/daily?date=2026-10-05').json()['timezone'] == 'America/Santiago'
    other, headers = as_user(state, 'intruso')
    assert other.get('/api/tasks/' + t['task_id']).status_code == 404
    assert other.get('/api/series/' + t['series_id']).status_code == 404
    assert other.post('/api/series/' + t['series_id'] + '/stop', headers={'x-csrf-token': headers['x-csrf-token']}).status_code == 404
    assert other.post('/api/push/subscriptions', json=subscription(), headers={'x-csrf-token': headers['x-csrf-token']}).status_code == 503
    assert api.c.get('/api/reminders/999').status_code == 404
    assert api.c.post('/api/reminders/999/snooze', json={'minutes': 10}, headers=api.h()).status_code == 404
    assert api.c.put('/api/settings', json={'local_only': True}, headers=api.h()).json()['local_only']
    assert api.c.get('/api/settings').json()['voice'] == {'enabled': True, 'stt': False, 'tts': False}
