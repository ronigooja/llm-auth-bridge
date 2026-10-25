"""Synthetic durable ordering and account-window contracts."""
import time
import pytest
from app.crypto import load_key
from app.db import database, migrate, SCHEMA_VERSION
from app.queue import Queue, Conflict
from app.worker import Worker


@pytest.fixture
def flow(settings, resources, admin):
    account, cli = resources
    voice = admin.post('/api/v1/targets', json={
        'kind': 'chatgpt-web-voice', 'name': 'Voice',
        'config': {'base_url': 'https://voice.example', 'admin_username': 'synthetic', 'admin_password': 'synthetic-secret'},
    }).json()['id']
    assert admin.patch(f'/api/v1/accounts/{account}', json={'target_ids': [voice, cli]}).status_code == 200
    return Queue(settings, load_key(settings.key_file)), account, voice, cli


def state(settings, task_id):
    with database(settings.db_path) as conn:
        return dict(conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())


def test_order_waits_for_verified_sync_and_retry(settings, flow):
    q, a, voice, cli = flow
    first, second = q.create_login_flow(a, voice, cli, 'flow-request')
    assert second['depends_on_task_id'] == first['id']
    claimed = q.claim()
    assert claimed['id'] == first['id']
    q.save_result(first['id'], claimed['execution_id'], {'synthetic': True})
    syncing = q.claim()
    assert syncing['id'] == first['id']
    with database(settings.db_path) as conn:
        conn.execute("UPDATE tasks SET phase='sync_failed',execution_id=NULL,lease_until=NULL WHERE id=?", (first['id'],))
    assert q.claim() is None
    q.action(first['id'], 'retry-sync')
    syncing = q.claim()
    q.finish(first['id'], syncing['execution_id'], 'succeeded', 'verified', 'Verified')
    assert q.claim()['id'] == second['id']


@pytest.mark.parametrize('outcome', ['failed', 'cancelled', 'interrupted'])
def test_failed_prerequisite_terminalizes_cli(settings, flow, outcome):
    q, a, voice, cli = flow
    first, second = q.create_login_flow(a, voice, cli)
    claimed = q.claim()
    q.finish(first['id'], claimed['execution_id'], outcome, outcome, 'Stopped')
    assert state(settings, second['id'])['phase'] == 'prerequisite_failed'
    assert q.claim() is None


def test_flow_idempotency_and_atomic_validation(settings, flow):
    q, a, voice, cli = flow
    with pytest.raises(Conflict):
        q.create_login_flow(a, cli, voice)
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    tasks = q.create_login_flow(a, voice, cli, 'same-request')
    assert q.create_login_flow(a, voice, cli, 'same-request') == tasks
    with pytest.raises(Conflict):
        q.create_login_flow(a, cli, voice, 'same-request')
    with pytest.raises(Conflict):
        q.create(a, cli, 'same-request')


def test_config_and_recovery_block_dependents(settings, flow, admin):
    q, a, voice, cli = flow
    first, second = q.create_login_flow(a, voice, cli)
    assert admin.delete(f'/api/v1/targets/{voice}').status_code == 409
    assert admin.patch(f'/api/v1/accounts/{a}', json={'password': 'changed-synthetic'}).status_code == 200
    assert q.claim() is None
    assert state(settings, first['id'])['phase'] == 'configuration_changed'
    assert state(settings, second['id'])['phase'] == 'prerequisite_failed'


def test_expired_prerequisite_and_missing_parent(settings, flow):
    q, a, voice, cli = flow
    first, second = q.create_login_flow(a, voice, cli)
    q.claim()
    with database(settings.db_path) as conn:
        conn.execute('UPDATE tasks SET lease_until=? WHERE id=?', (time.time()-1, first['id']))
    q.recover()
    assert state(settings, second['id'])['phase'] == 'prerequisite_failed'
    with database(settings.db_path) as conn:
        conn.execute("UPDATE tasks SET state='queued' WHERE id=?", (second['id'],))
        conn.execute('DELETE FROM tasks WHERE id=?', (first['id'],))
    assert q.claim() is None
    assert state(settings, second['id'])['state'] == 'interrupted'


def test_account_browser_reuses_live_task_and_has_no_target(settings, resources):
    a, cli = resources
    q = Queue(settings, load_key(settings.key_file))
    browser = q.open_browser(a, 'browser-request')
    assert browser['target_id'] is None
    assert q.open_browser(a)['id'] == browser['id']
    seen = []
    def runner(account, target, control, saved):
        assert target is None
        seen.append(account['id'])
    assert Worker(settings, runner=runner).run_once()
    assert seen == [a]
    assert state(settings, browser['id'])['state'] == 'succeeded'
    assert q.open_browser(a, 'browser-request')['id'] == browser['id']
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM pending_credentials').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM syncs').fetchone()[0] == 0
    login = q.create(a, cli)
    assert q.open_browser(a)['id'] == login['id']


def test_browser_opens_while_flow_sync_waits(settings, flow):
    q, a, voice, cli = flow
    first, second = q.create_login_flow(a, voice, cli)
    claimed = q.claim()
    q.save_result(first['id'], claimed['execution_id'], {'synthetic': True})
    browser = q.open_browser(a)
    assert browser['kind'] == 'browser_window'
    q.action(browser['id'], 'cancel')
    assert state(settings, browser['id'])['state'] == 'cancelled'


def test_v3_additive_migration(settings, resources):
    key = load_key(settings.key_file)
    with database(settings.db_path) as conn:
        conn.execute('DROP TABLE browser_requests')
        conn.execute('DROP TABLE login_flows')
        conn.execute('DROP INDEX task_dependency')
        conn.execute('ALTER TABLE tasks DROP COLUMN depends_on_task_id')
        conn.execute('PRAGMA user_version=3')
    migrate(settings.db_path, key)
    with database(settings.db_path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert conn.execute('SELECT count(*) FROM accounts').fetchone()[0] == 1
        assert 'depends_on_task_id' in [r[1] for r in conn.execute('PRAGMA table_info(tasks)')]


def test_flow_rejects_unbound_target_without_partial_insert(settings, flow, admin):
    q, a, voice, cli = flow
    assert admin.patch(f'/api/v1/accounts/{a}', json={'target_ids': [voice]}).status_code == 200
    with pytest.raises(Conflict, match='bind both'):
        q.create_login_flow(a, voice, cli)
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_browser_recovery_configuration_and_api(settings, resources, admin):
    a, _ = resources
    q = Queue(settings, load_key(settings.key_file))
    response = admin.post(f'/api/v1/accounts/{a}/browser')
    assert response.status_code == 200
    browser = response.json()['task']
    assert admin.delete(f'/api/v1/accounts/{a}').status_code == 409
    q.claim()
    with database(settings.db_path) as conn:
        conn.execute('UPDATE tasks SET lease_until=? WHERE id=?', (time.time()-1, browser['id']))
    q.recover()
    assert state(settings, browser['id'])['state'] == 'interrupted'
    next_browser = q.open_browser(a)
    assert admin.patch(f'/api/v1/accounts/{a}', json={'password': 'new-synthetic-password'}).status_code == 200
    assert q.claim() is None
    assert state(settings, next_browser['id'])['phase'] == 'configuration_changed'


def test_login_flow_api_returns_ordered_tasks(flow, admin):
    _, a, voice, cli = flow
    response = admin.post(f'/api/v1/accounts/{a}/login-flow', json={
        'voice_target_id': voice, 'cli_target_id': cli, 'idempotency_key': 'api-flow-request',
    })
    assert response.status_code == 200
    tasks = response.json()['tasks']
    assert [task['target_id'] for task in tasks] == [voice, cli]
    assert tasks[1]['depends_on_task_id'] == tasks[0]['id']


def test_browser_idempotency_tracks_reused_login(settings, resources):
    a, cli = resources
    q = Queue(settings, load_key(settings.key_file))
    login = q.create(a, cli)
    assert q.open_browser(a, 'reuse-request')['id'] == login['id']
    q.action(login['id'], 'cancel')
    assert q.open_browser(a, 'reuse-request')['id'] == login['id']
    with pytest.raises(Conflict):
        q.create(a, cli, 'reuse-request')
