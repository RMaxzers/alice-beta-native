"""Real SQLite tests with fixed instants: no LM, provider or live user data."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import json

import pytest
from pydantic import ValidationError

from apps.api.db import MIGRATIONS, connect, migrate
from packages.schemas.models import Recurrence, TaskIn, TaskPatch
from services.tasks.recurrence import next_date, wall_due
from services.tasks.reminders import ReminderService
from services.tasks.store import TaskError, TaskStore

NOW = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    con = connect(tmp_path / 'ops.db')
    migrate(con)
    yield TaskStore(con, 'America/Santiago')
    con.close()


def create(store, owner='ana', **kw):
    return store.create(owner, TaskIn(title=kw.pop('title', 'Agenda'), **kw), origin='user', actor=owner)['task']


@pytest.mark.parametrize('start,rule,want', [
    ('2026-10-05', {'freq': 'daily'}, '2026-10-06'),
    ('2026-10-09', {'freq': 'weekly', 'weekdays': [1, 3, 5]}, '2026-10-12'),
    ('2026-01-31', {'freq': 'monthly'}, '2026-02-28'),
    ('2028-01-31', {'freq': 'monthly'}, '2028-02-29'),
    ('2026-10-05', {'freq': 'daily', 'until': '2026-10-05'}, None),
])
def test_calendar_rules(start, rule, want):
    assert next_date(start, start, rule) == want


def test_monthly_anchor_survives_short_month_and_completion(store):
    t = create(store, due_date='2026-01-31', due_time='09:00', recurrence={'freq': 'monthly'})
    done = store.update('ana', t['task_id'], TaskPatch(version=1, status='done'), origin='user', actor='ana')
    feb = done['next']
    assert feb['due_date'] == '2026-02-28'
    assert feb['next_due']['due_date'] == '2026-03-31'
    march = store.update('ana', feb['task_id'], TaskPatch(version=1, status='done'), origin='user', actor='ana')['next']
    assert march['due_date'] == '2026-03-31' and march['series_id'] == t['series_id']
    assert len(store.list('ana', ['done'])['items']) == 2
    store.undo('ana', done['event_id'], actor='ana')
    assert store.get('ana', t['task_id'])['status'] == 'open'
    assert store.get('ana', march['task_id'])['status'] == 'open'


def test_duplicate_monthly_task_returns_true_series_anchor(store):
    recurring = create(store, due_date='2026-01-31', recurrence={'freq': 'monthly'})
    store.con.execute("UPDATE task_series SET cursor_date='2026-02-28' WHERE series_id=?", (recurring['series_id'],))
    store.con.execute("""INSERT INTO tasks(task_id,owner,title,description,status,priority,kind,due_date,due_time,timezone,
      origin,privacy,project,parent_id,position,sources_json,created_at,updated_at,version,series_id,occurrence_date,recurrence_json)
      SELECT 'feb','ana','Agenda','','open',3,'personal','2026-02-28',NULL,timezone,'user','PRIVATE',NULL,NULL,1,'[]',
      'now','now',1,series_id,'2026-02-28',recurrence_json FROM tasks WHERE task_id=?""", (recurring['task_id'],))
    duplicate = create(store, due_date='2026-02-28', recurrence={'freq': 'monthly'})
    assert duplicate['task_id'] == 'feb' and duplicate['next_due']['due_date'] == '2026-03-31'


@pytest.mark.parametrize('rule', [
    {'freq': 'weekly'}, {'freq': 'weekly', 'weekdays': [0]}, {'freq': 'weekly', 'weekdays': [1, 1]},
    {'freq': 'daily', 'weekdays': [1]}, {'freq': 'yearly'}, {'freq': 'daily', 'interval': 2},
    {'freq': 'daily', 'until': '2026-02-30'},
])
def test_invalid_recurrence(rule):
    with pytest.raises(ValidationError):
        Recurrence(**rule)


@pytest.mark.parametrize('kw', [
    {}, {'due_date': '2026-10-05', 'status': 'draft'},
    {'due_date': '2026-10-05', 'recurrence': {'freq': 'weekly', 'weekdays': [2]}},
    {'due_date': '2026-10-05', 'recurrence': {'freq': 'daily', 'until': '2026-10-04'}},
])
def test_invalid_start_rolls_back(store, kw):
    with pytest.raises(TaskError) as exc:
        create(store, **{'recurrence': {'freq': 'daily'}, **kw})
    assert exc.value.status == 422
    assert store.con.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    assert store.con.execute('SELECT COUNT(*) FROM task_series').fetchone()[0] == 0


def test_catchup_independent_of_completion_and_restart(store, tmp_path):
    t = create(store, due_date='2026-10-01', due_time='09:00', recurrence={'freq': 'daily', 'until': '2026-10-07'})
    worker = ReminderService(store.con, True)
    assert worker.tick(NOW) == 5
    assert store.list('ana')['total'] == 7
    other = connect(tmp_path / 'ops.db')
    try:
        assert ReminderService(other, True).tick(NOW + timedelta(minutes=1)) == 0
        assert other.execute('SELECT COUNT(*) FROM task_reminders').fetchone()[0] == 5
        assert other.execute('SELECT COUNT(DISTINCT task_id) FROM task_reminders').fetchone()[0] == 5
        assert store.get('ana', t['task_id'])['status'] == 'open'
    finally:
        other.close()


def test_concurrent_workers_dont_duplicate(store, tmp_path):
    create(store, due_date='2026-10-05', due_time='09:00', recurrence={'freq': 'daily'})
    def work(_):
        con = connect(tmp_path / 'ops.db')
        try:
            return ReminderService(con, True).tick(NOW)
        finally:
            con.close()
    with ThreadPoolExecutor(4) as pool:
        assert sum(pool.map(work, range(8))) == 1
    assert store.list('ana')['total'] == 8


def test_atomic_completion_failure_preserves_series_cursor(store, monkeypatch):
    t = create(store, due_date='2026-10-05', recurrence={'freq': 'daily'})
    monkeypatch.setattr(store, '_event', lambda *a: (_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError):
        store.update('ana', t['task_id'], TaskPatch(version=1, status='done'), origin='user', actor='ana')
    assert store.get('ana', t['task_id'])['status'] == 'open'
    assert store.list('ana')['total'] == 1
    assert store.con.execute('SELECT cursor_date FROM task_series').fetchone()[0] == '2026-10-06'


@pytest.mark.parametrize('day,clock,utc', [
    ('2026-09-06', '00:30', '2026-09-06T04:30:00+00:00'),
    ('2026-04-04', '23:30', '2026-04-05T02:30:00+00:00'),
])
def test_santiago_dst_gap_fold_one_notice(store, day, clock, utc):
    t = create(store, due_date=day, due_time=clock)
    when = datetime.fromisoformat(utc)
    assert wall_due(day, clock, 'America/Santiago') == when
    service = ReminderService(store.con, True)
    assert service.tick(when - timedelta(seconds=1)) == 0
    assert service.tick(when) == 1
    assert ReminderService(store.con, True).tick(when + timedelta(hours=2)) == 0
    assert store.con.execute('SELECT COUNT(*) FROM task_reminders WHERE task_id=?', (t['task_id'],)).fetchone()[0] == 1


def test_snooze_history_restart_and_ack(store):
    t = create(store, due_date='2026-10-05', due_time='09:00')
    service = ReminderService(store.con, True)
    service.tick(NOW)
    rid = service.list('ana')['items'][0]['reminder_id']
    first = service.snooze('ana', rid, minutes=10, now=NOW)
    assert first['generation'] == 1 and service.list('ana')['unread'] == 0
    assert ReminderService(store.con, True).tick(NOW + timedelta(minutes=9)) == 0
    assert ReminderService(store.con, True).tick(NOW + timedelta(minutes=10)) == 1
    assert service.list('ana')['unread'] == 1
    service.acknowledge('ana', rid)
    service.snooze('ana', rid, minutes=60, now=NOW + timedelta(minutes=11))
    target = NOW + timedelta(days=1)
    service.snooze('ana', rid, until=target.isoformat(), now=NOW)
    same = service.snooze('ana', rid, until=target.isoformat(), now=NOW)
    assert same['generation'] == 3
    assert service.tick(target) == 1 and service.tick(target) == 0
    assert [x['kind'] for x in service.get('ana', rid)['history']] == ['fired', 'snoozed', 'fired', 'read', 'snoozed', 'snoozed', 'fired']
    assert store.con.execute('SELECT COUNT(*) FROM task_reminders').fetchone()[0] == 1
    store.update('ana', t['task_id'], TaskPatch(version=1, status='done'), origin='user', actor='ana')
    with pytest.raises(TaskError) as exc:
        service.snooze('ana', rid, minutes=10, now=NOW)
    assert exc.value.status == 409 and service.list('ana')['items'] == []
    assert len(service.get('ana', rid)['history']) == 7


def test_acknowledging_snoozed_notice_cancels_future_wakeup(store):
    create(store, due_date='2026-10-05', due_time='09:00')
    service = ReminderService(store.con, True)
    service.tick(NOW)
    rid = service.list('ana')['items'][0]['reminder_id']
    service.snooze('ana', rid, minutes=10, now=NOW)
    service.acknowledge('ana', rid)
    assert service.tick(NOW + timedelta(hours=1)) == 0
    assert service.list('ana')['unread'] == 0
    assert service.get('ana', rid)['snoozed_until'] is None


@pytest.mark.parametrize('kw', [{'minutes': 5}, {}, {'minutes': 10, 'until': '2026-10-06T12:00:00Z'},
    {'until': '2026-10-06T12:00:00'}, {'until': '2026-10-05T01:00:00Z'}, {'until': 'bad'}])
def test_snooze_validation(store, kw):
    with pytest.raises(TaskError) as exc:
        ReminderService(store.con, True).snooze('ana', 1, now=NOW, **kw)
    assert exc.value.status == 422


def test_reschedule_cannot_duplicate_logical_notice(store):
    t = create(store, due_date='2026-10-05', due_time='09:00')
    r = ReminderService(store.con, True)
    r.tick(NOW)
    store.update('ana', t['task_id'], TaskPatch(version=1, due_time='10:00'), origin='user', actor='ana')
    assert r.tick(NOW) == 0 and r.list('ana')['items'] == []
    assert store.con.execute('SELECT COUNT(*) FROM task_reminders').fetchone()[0] == 1


def test_stop_series_and_attach_existing(store):
    t = create(store, due_date='2090-10-05')
    t = store.update('ana', t['task_id'], TaskPatch(version=1, recurrence={'freq': 'daily'}), origin='user', actor='ana')['task']
    r = ReminderService(store.con, False)
    r.tick(datetime(2090, 10, 5, tzinfo=timezone.utc))
    store.stop_series('ana', t['series_id'])
    assert not store.series('ana', t['series_id'])['active']
    assert store.list('ana')['total'] == 0
    assert store.get('ana', t['task_id'])['next_due'] is None
    r.tick(datetime(2090, 11, 5, tzinfo=timezone.utc))
    assert store.list('ana')['total'] == 0


def test_series_create_is_not_advertised_as_undoable(store):
    t = create(store, due_date='2026-10-05', recurrence={'freq': 'daily'})
    assert store.events('ana', t['task_id'])[0]['undoable'] is False
    with pytest.raises(TaskError) as exc:
        store.undo('ana', store.events('ana', t['task_id'])[0]['event_id'], actor='ana')
    assert exc.value.status == 409


def test_summary_counts_not_limited_and_no_cross_user(store):
    for i in range(8):
        create(store, title=f'Late{i}', due_date='2026-10-04')
    create(store, title='Today late', due_date='2026-10-05', due_time='09:00')
    create(store, title='Today', due_date='2026-10-05', due_time='23:00')
    create(store, title='Undated')
    create(store, title='Soon', due_date='2026-10-12')
    create(store, title='Far', due_date='2026-10-13')
    create(store, title='Draft', status='draft')
    create(store, owner='beto', title='Private', due_date='2026-10-01')
    result = store.daily_summary('ana', now=NOW)
    assert result['counts'] == {'pending': 2, 'overdue': 9, 'upcoming': 1}
    assert len(result['overdue']) == 5 and result['next']['due_date'] == '2026-10-04'
    assert all(t['title'] != 'Private' for key in ('overdue', 'today', 'upcoming') for t in result[key])


def test_migration_v7_preserves_tasks_events_reminders(tmp_path):
    con = connect(tmp_path / 'legacy.db')
    for i, sql in enumerate(MIGRATIONS[:7], 1):
        con.executescript(f'BEGIN;{sql};PRAGMA user_version={i};COMMIT;')
    con.execute("""INSERT INTO tasks VALUES ('old','ana','Legacy','','open',3,'personal','2026-10-05','09:00',
      'America/Santiago','user','PRIVATE',NULL,NULL,1,'[]',NULL,'before','before',NULL,1)""")
    con.execute("INSERT INTO task_events(task_id,owner,at,actor,origin,op) VALUES ('old','ana','before','ana','user','create')")
    con.execute("INSERT INTO task_reminders VALUES (1,'ana','old','2026-10-05','09:00','America/Santiago','before','before',NULL)")
    originals = {table: dict(con.execute(f'SELECT * FROM {table}').fetchone()) for table in ('tasks', 'task_events', 'task_reminders')}
    assert migrate(con) == 8 and migrate(con) == 8
    for table, before in originals.items():
        after = dict(con.execute(f'SELECT * FROM {table}').fetchone())
        assert all(after[k] == v for k, v in before.items())
    assert ReminderService(con, True).tick(NOW) == 0
    con.close()

