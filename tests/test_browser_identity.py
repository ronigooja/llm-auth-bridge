"""Synthetic-only checks for encrypted account-scoped native browser identity."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import time
import pytest
from app.browser_identity import context_options, generate_profile, load_or_create_profile
from app.cli import backup, restore
from app.crypto import decrypt, encrypt, load_key
from app.db import SCHEMA_VERSION, database, migrate, validate_database
from app.queue import Cancelled, LeaseLost, Queue
from app.worker import Worker


def claimed(settings, account_id, target_id):
    key = load_key(settings.key_file)
    queue = Queue(settings, key)
    queue.create(account_id, target_id)
    return key, queue, queue.claim()


def profile_for(settings, key, queue, task):
    return load_or_create_profile(settings.db_path, key, queue, task)


def test_native_options_independent_seeds_coherent_private():
    first = generate_profile(set())
    options = context_options(first)
    second = generate_profile({(options['viewport']['width'], options['viewport']['height'])})
    assert first['identity_seed'] != second['identity_seed']
    assert options['viewport'] == context_options(second)['viewport'] == {'width': 1760, 'height': 900}
    assert options['screen'] == {'width': 1920, 'height': 1080}
    assert options['screen']['height'] > options['viewport']['height']
    assert options['device_scale_factor'] == 1
    assert options['is_mobile'] is False and options['has_touch'] is False
    assert options['locale'] == 'en-US' and options['timezone_id'] == 'UTC'
    assert 'identity_seed' not in options and 'user_agent' not in options
    options['viewport']['width'] = 1
    assert context_options(first)['viewport']['width'] >= 1200


def test_first_use_atomic_and_encrypted(settings, resources):
    key, queue, task = claimed(settings, *resources)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: profile_for(settings, key, queue, task), range(2)))
    assert results[0] == results[1]
    with database(settings.db_path) as conn:
        rows = conn.execute('SELECT * FROM browser_profiles').fetchall()
    assert len(rows) == 1 and rows[0]['account_id'] == resources[0]
    assert json.loads(decrypt(rows[0]['profile_cipher'], key)) == results[0]
    assert results[0]['identity_seed'] not in rows[0]['profile_cipher']
    assert results[0]['identity_seed'].encode() not in settings.db_path.read_bytes()


def test_stale_cancelled_owner_cannot_allocate(settings, resources):
    key, queue, task = claimed(settings, *resources)
    with database(settings.db_path) as conn:
        conn.execute('UPDATE tasks SET lease_until=? WHERE id=?', (time.time() - 1, task['id']))
    with pytest.raises(LeaseLost):
        profile_for(settings, key, queue, task)
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM browser_profiles').fetchone()[0] == 0
        conn.execute('UPDATE tasks SET lease_until=?,cancel_requested=1 WHERE id=?', (time.time() + 60, task['id']))
    with pytest.raises(Cancelled):
        profile_for(settings, key, queue, task)
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM browser_profiles').fetchone()[0] == 0


def test_lease_expiring_during_generation_rolls_back(settings, resources, monkeypatch):
    key, queue, task = claimed(settings, *resources)
    original = queue.owned
    checks = []
    def fenced(*args):
        checks.append(True)
        if len(checks) > 1:
            raise LeaseLost()
        return original(*args)
    monkeypatch.setattr(queue, 'owned', fenced)
    with pytest.raises(LeaseLost):
        profile_for(settings, key, queue, task)
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT count(*) FROM browser_profiles').fetchone()[0] == 0


def test_failed_login_restart_edits_and_voice_share_identity(settings, resources, admin):
    account_id, target_id = resources
    profiles = []
    def fail_login(account, target, control, saved):
        profiles.append(account['_browser_profile'])
        raise RuntimeError('synthetic login failure')
    key = load_key(settings.key_file)
    queue = Queue(settings, key)
    queue.create(account_id, target_id)
    assert Worker(settings, runner=fail_login).run_once()
    assert len(profiles) == 1
    response = admin.patch(f'/api/v1/accounts/{account_id}', json={
        'username': 'changed@example.com', 'password': 'replacement-synthetic',
        'route_type': 'proxy', 'proxy': {'server': 'http://proxy.example:8080'},
    })
    assert response.status_code == 200, response.text
    voice = admin.post('/api/v1/targets', json={
        'kind': 'chatgpt-web-voice', 'name': 'Synthetic voice',
        'config': {'base_url': 'https://voice.example', 'admin_username': 'synthetic-admin', 'admin_password': 'synthetic-password'},
    })
    assert voice.status_code == 200, voice.text
    response = admin.patch(f'/api/v1/accounts/{account_id}', json={'target_ids': [target_id, voice.json()['id']]})
    assert response.status_code == 200, response.text
    for destination in (target_id, voice.json()['id']):
        queue.create(account_id, destination)
        assert Worker(settings, runner=fail_login).run_once()
    assert profiles == [profiles[0]] * 3
    public = admin.get('/api/v1/accounts').text
    assert 'identity_seed' not in public and profiles[0]['identity_seed'] not in public


def test_accounts_distinct_delete_cascades_recreate_has_new_seed(settings, resources, admin):
    account_id, target_id = resources
    key, queue, task = claimed(settings, account_id, target_id)
    first = profile_for(settings, key, queue, task)
    queue.finish(task['id'], task['execution_id'], 'failed', 'failed', 'Synthetic failure')
    payload = {'username': 'second@example.com', 'password': 'synthetic-password',
               'route_type': 'direct', 'target_ids': [target_id]}
    response = admin.post('/api/v1/accounts', json=payload)
    assert response.status_code == 200, response.text
    second_id = response.json()['id']
    _, _, task = claimed(settings, second_id, target_id)
    second = profile_for(settings, key, queue, task)
    assert first['identity_seed'] != second['identity_seed']
    assert context_options(first)['viewport'] == context_options(second)['viewport']
    queue.finish(task['id'], task['execution_id'], 'failed', 'failed', 'Synthetic failure')
    assert admin.delete(f'/api/v1/accounts/{second_id}').status_code == 200
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT 1 FROM browser_profiles WHERE account_id=?', (second_id,)).fetchone() is None
    recreated = admin.post('/api/v1/accounts', json=payload)
    assert recreated.status_code == 200, recreated.text
    _, _, task = claimed(settings, recreated.json()['id'], target_id)
    assert profile_for(settings, key, queue, task)['identity_seed'] != second['identity_seed']


def test_backup_restore_preserves_encrypted_profile_and_state(settings, resources, tmp_path):
    key, queue, task = claimed(settings, *resources)
    original = profile_for(settings, key, queue, task)
    state = {'cookies': [{'name': 'synthetic', 'value': 'synthetic-state'}], 'origins': []}
    with database(settings.db_path) as conn:
        conn.execute('INSERT INTO browser_sessions VALUES(?,?,?)', (resources[0], encrypt(json.dumps(state), key), time.time()))
    archive = tmp_path / 'identity-backup.db'
    backup(settings, archive)
    restored = replace(settings, db_path=tmp_path / 'restored' / 'bridge.db')
    restore(restored, archive)
    assert profile_for(restored, key, Queue(restored, key), task) == original
    with database(restored.db_path) as conn:
        assert json.loads(decrypt(conn.execute('SELECT state_cipher FROM browser_sessions').fetchone()[0], key)) == state


def version_one(settings, account_id, key):
    cipher = encrypt(json.dumps({'cookies': [], 'origins': []}), key)
    with database(settings.db_path) as conn:
        conn.execute('DROP TABLE browser_requests')
        conn.execute('DROP TABLE login_flows')
        conn.execute('DROP INDEX task_dependency')
        conn.execute('ALTER TABLE tasks DROP COLUMN depends_on_task_id')
        conn.execute('DROP TABLE browser_devices')
        conn.execute('DROP TABLE browser_profiles')
        conn.execute('DROP TABLE native_sessions')
        conn.execute('PRAGMA user_version=1')
        conn.execute('INSERT INTO browser_sessions VALUES(?,?,?)', (account_id, cipher, 123))
    return cipher


def test_v1_explicit_migration_preserves_accounts_and_sessions(settings, resources):
    key = load_key(settings.key_file)
    cipher = version_one(settings, resources[0], key)
    with pytest.raises(RuntimeError, match='explicit migrate'):
        validate_database(settings.db_path, key)
    migrate(settings.db_path, key)
    validate_database(settings.db_path, key)
    with database(settings.db_path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert conn.execute('SELECT state_cipher FROM browser_sessions').fetchone()[0] == cipher
        assert decrypt(conn.execute('SELECT password_cipher FROM accounts').fetchone()[0], key) == 'synthetic-password'
        assert conn.execute('SELECT count(*) FROM browser_profiles').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM native_sessions').fetchone()[0] == 0
    migrate(settings.db_path, key)


def test_v1_wrong_key_rolls_back_schema_and_sessions(settings, resources):
    key = load_key(settings.key_file)
    cipher = version_one(settings, resources[0], key)
    with pytest.raises(ValueError):
        migrate(settings.db_path, os.urandom(32))
    with database(settings.db_path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='browser_profiles'").fetchone() is None
        assert conn.execute('SELECT state_cipher FROM browser_sessions').fetchone()[0] == cipher


def legacy_profile(settings, account_id, key):
    profile = generate_profile()
    profile['version'] = 1
    profile['context'].update(
        viewport={'width': 1777, 'height': 1111},
        screen={'width': 1777, 'height': 1191},
        locale='fr-FR', timezone_id='Europe/Paris', color_scheme='dark',
    )
    cipher = encrypt(json.dumps(profile), key)
    with database(settings.db_path) as conn:
        conn.execute('INSERT INTO browser_profiles(account_id,profile_cipher) VALUES(?,?)', (account_id, cipher))
    return profile, cipher


def test_profile_v1_upgrade_preserves_seed_preferences_and_cipher_once(settings, resources):
    key, queue, task = claimed(settings, *resources)
    legacy, old_cipher = legacy_profile(settings, resources[0], key)
    upgraded = profile_for(settings, key, queue, task)
    assert upgraded['version'] == 4
    assert upgraded['browser'] == {'platform': 'windows'}
    assert upgraded['identity_seed'] == legacy['identity_seed']
    assert upgraded['camoufox']
    expected = dict(legacy['context'])
    expected.update(viewport={'width': 1760, 'height': 900}, screen={'width': 1920, 'height': 1080})
    options = context_options(upgraded)
    assert {k: v for k, v in options.items() if k != 'config'} == expected
    assert options['config'] == upgraded['camoufox']
    with database(settings.db_path) as conn:
        row = conn.execute('SELECT * FROM browser_profiles').fetchone()
    assert row['account_id'] == resources[0]
    assert row['profile_cipher'] != old_cipher
    assert json.loads(decrypt(row['profile_cipher'], key)) == upgraded
    assert profile_for(settings, key, queue, task) == upgraded
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT profile_cipher FROM browser_profiles').fetchone()[0] == row['profile_cipher']


@pytest.mark.parametrize('failure', ['lease', 'cancel'])
def test_profile_upgrade_fenced_before_write(settings, resources, monkeypatch, failure):
    key, queue, task = claimed(settings, *resources)
    _, cipher = legacy_profile(settings, resources[0], key)
    original = queue.owned
    calls = []
    def fenced(*args):
        owned = original(*args)
        calls.append(True)
        if len(calls) == 2:
            if failure == 'lease':
                raise LeaseLost()
            return dict(owned, cancel_requested=1)
        return owned
    monkeypatch.setattr(queue, 'owned', fenced)
    with pytest.raises(LeaseLost if failure == 'lease' else Cancelled):
        profile_for(settings, key, queue, task)
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT profile_cipher FROM browser_profiles').fetchone()[0] == cipher


def test_platform_api_preserves_existing_device_and_seed(settings, resources, admin):
    account_id, target_id = resources
    key, queue, task = claimed(settings, account_id, target_id)
    original = profile_for(settings, key, queue, task)
    endpoint = f'/api/v1/accounts/{account_id}/browser-identity'
    assert admin.get(endpoint).json() == {'platform': 'windows'}
    assert admin.put(endpoint, json={'platform': 'macos'}).status_code == 409
    queue.finish(task['id'], task['execution_id'], 'failed', 'failed', 'Synthetic failure')
    # The device archive and saved sessions are deliberately not edited here.
    with database(settings.db_path) as conn:
        conn.execute('INSERT INTO browser_devices(account_id,archive_cipher,updated_at) VALUES(?,?,?)',
                     (account_id, b'synthetic-encrypted-device', time.time()))
    response = admin.put(endpoint, json={'platform': 'macos'})
    assert response.status_code == 200, response.text
    assert response.json() == admin.get(endpoint).json() == {'platform': 'macos'}
    with database(settings.db_path) as conn:
        updated = json.loads(decrypt(conn.execute('SELECT profile_cipher FROM browser_profiles WHERE account_id=?', (account_id,)).fetchone()[0], key))
        assert updated['identity_seed'] == original['identity_seed']
        assert updated['context'] == original['context']
        assert conn.execute('SELECT archive_cipher FROM browser_devices WHERE account_id=?', (account_id,)).fetchone()[0] == b'synthetic-encrypted-device'
    assert admin.put(endpoint, json={'platform': 'linux'}).status_code == 422
    assert admin.put(endpoint, json={'platform': 'windows', 'user_agent': 'arbitrary'}).status_code == 422
    assert 'identity_seed' not in response.text


def test_version_two_upgrade_preserves_device_preferences(settings, resources):
    key, queue, task = claimed(settings, *resources)
    old = generate_profile()
    old['version'] = 2
    old.pop('browser')
    with database(settings.db_path) as conn:
        conn.execute('INSERT INTO browser_profiles(account_id,profile_cipher) VALUES(?,?)',
                     (resources[0], encrypt(json.dumps(old), key)))
    upgraded = profile_for(settings, key, queue, task)
    assert upgraded['version'] == 4
    assert upgraded['browser'] == {'platform': 'windows'}
    assert upgraded['identity_seed'] == old['identity_seed']
    assert upgraded['context'] == old['context']


def test_camoufox_config_is_stable_and_replayed():
    first = generate_profile()
    second = json.loads(json.dumps(first))
    assert context_options(first)['config'] == context_options(second)['config']
    assert 'user_agent' not in context_options(first)
