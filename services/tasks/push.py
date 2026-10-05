"""Opt-in Web Push with leased durable outbox. No task text leaves Alice."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from apps.api.db import tx
from services.tasks.store import TaskError

log = logging.getLogger('alice.push')


def decode_key(value):
    return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)


def validate_endpoint(endpoint):
    try:
        u = urlsplit(endpoint)
        host = u.hostname or ''
        allowed = (host in ('fcm.googleapis.com', 'android.googleapis.com', 'updates.push.services.mozilla.com')
                   or host.endswith('.push.services.mozilla.com') or host == 'push.apple.com'
                   or host.endswith('.push.apple.com')
                   or host.endswith('.notify.windows.com'))
        if (u.scheme != 'https' or not allowed or u.port not in (None, 443) or u.username or u.password
                or u.fragment or not u.path or any(c.isspace() for c in endpoint)):
            raise ValueError()
    except ValueError as exc:
        raise TaskError(422, 'Endpoint Push HTTPS de proveedor no admitido') from exc


class PushService:
    def __init__(self, con, settings, sender=None):
        self.con, self.settings = con, settings
        self.sender = sender or self._send
        self.reason = 'Web Push desactivado'
        self.enabled = False
        if settings.alice_push_enabled:
            try:
                from cryptography.hazmat.primitives import serialization
                from cryptography.hazmat.primitives.asymmetric import ec
                private = serialization.load_pem_private_key(settings.alice_push_private_key.read_bytes(), password=None)
                if not isinstance(private, ec.EllipticCurvePrivateKey) or not isinstance(private.curve, ec.SECP256R1):
                    raise ValueError()
                public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
                if public != decode_key(settings.alice_push_public_key):
                    raise ValueError()
                subject = settings.alice_push_subject
                if not (subject.startswith('mailto:') and '@' in subject or subject.startswith('https://')):
                    raise ValueError()
                self.enabled, self.reason = True, None
            except Exception:
                self.reason = 'Configura claves VAPID P-256 coincidentes y subject de contacto'

    def config(self):
        return {'enabled': self.enabled, 'vapid_public_key': self.settings.alice_push_public_key if self.enabled else None,
                'reason': self.reason}

    def subscribe(self, owner, body):
        if not self.enabled:
            raise TaskError(503, self.reason)
        validate_endpoint(body['endpoint'])
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode_key(body['keys']['p256dh']))
            if len(decode_key(body['keys']['auth'])) != 16:
                raise ValueError()
        except (ValueError, TypeError, KeyError) as exc:
            raise TaskError(422, 'Claves de suscripción no válidas') from exc
        now = datetime.now(timezone.utc)
        expires = body.get('expirationTime')
        # Some engines return a monotonic DOMHighResTimeStamp; it is not an
        # epoch. Only clean values that are unambiguously Unix milliseconds.
        if expires is not None:
            if expires < 946684800000:  # 2000-01-01 UTC
                expires = None
            elif expires <= now.timestamp() * 1000:
                raise TaskError(422, 'La suscripción ya venció')
        with tx(self.con):
            self._cleanup(now)
            row = self.con.execute('SELECT * FROM push_subscriptions WHERE endpoint=?', (body['endpoint'],)).fetchone()
            if row and row['owner'] != owner:
                raise TaskError(409, 'Suscripción no disponible; cancela la suscripción del navegador y vuelve a activar')
            if not row and self.con.execute('SELECT COUNT(*) FROM push_subscriptions WHERE owner=?', (owner,)).fetchone()[0] >= 20:
                raise TaskError(409, 'Máximo 20 dispositivos; elimina uno primero')
            sid = row['subscription_id'] if row else uuid.uuid4().hex
            self.con.execute('''INSERT INTO push_subscriptions VALUES (?,?,?,?,?,?,?)
              ON CONFLICT(endpoint) DO UPDATE SET keys_json=excluded.keys_json,expiration_ms=excluded.expiration_ms,device_label=excluded.device_label''',
              (sid, owner, body['endpoint'], json.dumps(body['keys']), expires, body.get('device_label') or '', now.isoformat()))
        return {'subscription_id': sid}

    def list(self, owner):
        return {'items': [dict(r) for r in self.con.execute('''SELECT subscription_id,endpoint,device_label,created_at,
          expiration_ms AS expirationTime FROM push_subscriptions WHERE owner=?
          AND (expiration_ms IS NULL OR expiration_ms>?)''', (owner, datetime.now(timezone.utc).timestamp() * 1000))]}

    def unsubscribe(self, owner, endpoint):
        with tx(self.con):
            result = self.con.execute('DELETE FROM push_subscriptions WHERE owner=? AND endpoint=?', (owner, endpoint))
            if not result.rowcount:
                raise TaskError(404, 'Suscripción no encontrada')
        return {'ok': True}

    def _cleanup(self, now):
        self.con.execute('DELETE FROM push_subscriptions WHERE expiration_ms IS NOT NULL AND expiration_ms<=?', (now.timestamp() * 1000,))

    def _claim(self, now):
        with tx(self.con):
            self._cleanup(now)
            row = self.con.execute('''SELECT d.*,s.owner,s.endpoint,s.keys_json,r.task_id,r.generation AS current_generation,
              r.read_at,r.snoozed_until,t.status AS task_status,t.due_date,t.due_time,t.timezone,
              r.due_date AS reminder_date,r.due_time AS reminder_time,r.timezone AS reminder_zone
              FROM push_deliveries d JOIN push_subscriptions s USING(subscription_id)
              JOIN task_reminders r ON r.reminder_id=d.reminder_id AND r.owner=s.owner
              JOIN tasks t ON t.task_id=r.task_id AND t.owner=r.owner
              WHERE d.status IN ('pending','sending') AND d.available_at<=? ORDER BY d.delivery_id LIMIT 1''',
              (now.isoformat(),)).fetchone()
            if row is None:
                return None
            valid = (row['current_generation'] == row['generation'] and not row['read_at'] and not row['snoozed_until']
                     and row['task_status'] in ('open','in_progress') and row['due_date'] == row['reminder_date']
                     and row['due_time'] == row['reminder_time'] and row['timezone'] == row['reminder_zone'])
            if not valid:
                self.con.execute("UPDATE push_deliveries SET status='cancelled' WHERE delivery_id=?", (row['delivery_id'],))
                return {}
            token = uuid.uuid4().hex
            self.con.execute("UPDATE push_deliveries SET status='sending',attempts=attempts+1,lease_token=?,available_at=? WHERE delivery_id=?",
                             (token, (now + timedelta(seconds=90)).isoformat(), row['delivery_id']))
            return {**dict(row), 'lease_token': token, 'attempts': row['attempts'] + 1}

    def _send(self, subscription, payload):
        from pywebpush import webpush, WebPushException
        import requests

        class NoRedirectSession(requests.Session):
            def request(self, *args, **kwargs):
                kwargs['allow_redirects'] = False
                return super().request(*args, **kwargs)

        validate_endpoint(subscription['endpoint'])
        with NoRedirectSession() as session:
            session.trust_env = False
            try:
                response = webpush(subscription_info=subscription, data=json.dumps(payload),
                    vapid_private_key=str(self.settings.alice_push_private_key),
                    vapid_claims={'sub': self.settings.alice_push_subject}, ttl=86400, timeout=10,
                    requests_session=session)
                return response.status_code
            except WebPushException as exc:
                if exc.response is not None:
                    return exc.response.status_code
                raise

    def tick(self, now=None, limit=20):
        now = now or datetime.now(timezone.utc)
        if not self.enabled:
            with tx(self.con):
                self._cleanup(now)
            return 0
        count = 0
        for _ in range(limit):
            row = self._claim(now)
            if row is None:
                break
            if not row:
                continue
            rid, tid = row['reminder_id'], row['task_id']
            payload = {'title': 'Alice', 'body': 'Tienes un recordatorio pendiente', 'tag': f'alice-reminder-{rid}',
                       'url': f'/#today?task={tid}&reminder={rid}', 'task_id': tid, 'reminder_id': rid, 'generation': row['generation']}
            try:
                status = self.sender({'endpoint': row['endpoint'], 'keys': json.loads(row['keys_json'])}, payload)
                error = None if 200 <= status < 300 else f'HTTP {status}'
            except Exception:
                status, error = 0, 'Fallo de transporte'
            with tx(self.con):
                if status in (404, 410):
                    self.con.execute('DELETE FROM push_subscriptions WHERE subscription_id=? AND owner=?', (row['subscription_id'], row['owner']))
                else:
                    result = 'sent' if 200 <= status < 300 else 'pending'
                    if result == 'pending' and (row['attempts'] >= 10 or (400 <= status < 500 and status not in (408, 429)) or 300 <= status < 400):
                        result = 'failed'
                    self.con.execute('''UPDATE push_deliveries SET status=?,last_error=?,available_at=?
                      WHERE delivery_id=? AND lease_token=? AND status='sending' ''',
                      (result, error, (now + timedelta(seconds=min(3600, 60 * 2 ** min(row['attempts'] - 1, 6)))).isoformat(), row['delivery_id'], row['lease_token']))
            count += 1
        return count

    async def loop(self):
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.error('No se pudo procesar la cola Push')  # never log endpoints or keys
            await asyncio.sleep(15)
