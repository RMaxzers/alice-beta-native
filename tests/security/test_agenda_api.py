"""Agenda and push routes share existing cookie + CSRF behavior."""
import pytest


@pytest.mark.parametrize('method,path,body', [
    ('POST','/api/reminders/1/snooze',{'minutes':10}),
    ('POST','/api/push/subscriptions',{}),
    ('DELETE','/api/push/subscriptions',{'endpoint':'https://fcm.googleapis.com/x'}),
    ('POST','/api/series/x/stop',None),
])
def test_agenda_writes_require_csrf(client, api, method, path, body):
    assert client.request(method, path, json=body).status_code == 403


def test_reminder_read_requires_auth(client):
    assert client.get('/api/reminders/999').status_code == 401
    assert client.get('/api/summary/daily').status_code == 401
    assert client.get('/api/push/config').status_code == 401
