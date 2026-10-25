"""Synthetic leased device storage and schema-upgrade regression checks."""
import json
import os
import sqlite3
import time
from dataclasses import replace

import pytest
from app.crypto import decrypt, encrypt, load_key
from app.db import database, migrate, validate_database, SCHEMA_VERSION
from app.queue import Queue, LeaseLost
from app.worker import Worker, Control
from app.cli import backup, restore


def control_for(settings, account_id, target_id):
    worker = Worker(settings)
    worker.queue.create(account_id, target_id)
    task = worker.queue.claim()
    worker.load(task)
    return worker, task, Control(worker, task)


def test_account_device_encrypted_fenced_and_cross_target(settings, resources, admin):
    account, target = resources
    worker, task, control = control_for(settings, account, target)
    assert control.load_device() is None
    archive = b'synthetic-archive-with-cookie-credentials'
    control.save_device(archive)
    assert control.load_device() == archive
    with database(settings.db_path) as conn:
        stored = conn.execute('SELECT archive_cipher FROM browser_devices').fetchone()[0]
        assert archive not in stored
    assert archive not in settings.db_path.read_bytes()
    worker.queue.finish(task['id'], task['execution_id'], 'succeeded', 'done', 'Synthetic')
    voice = admin.post('/api/v1/targets', json={
        'kind': 'chatgpt-web-voice', 'name': 'Voice',
        'config': {'base_url': 'https://voice.example', 'admin_username': 'synthetic', 'admin_password': 'synthetic-password'},
    }).json()['id']
    assert admin.patch(f'/api/v1/accounts/{account}', json={'target_ids': [target, voice]}).status_code == 200
    worker2, task2, control2 = control_for(settings, account, voice)
    assert control2.load_device() == archive
    # Cancellation preserves device progress, but does not authorize provider work.
    worker2.queue.action(task2['id'], 'cancel')
    control2.save_device(b'synthetic-progress-before-cancellation')
    with pytest.raises(Exception):
        control2.checkpoint()
    with database(settings.db_path) as conn:
        conn.execute('UPDATE tasks SET lease_until=? WHERE id=?', (time.time()-1, task2['id']))
    with pytest.raises(LeaseLost):
        control2.save_device(b'stale-owner')
    with pytest.raises(LeaseLost):
        control2.load_device()


def test_device_cipher_bound_to_account_and_delete_cascades(settings, resources, admin):
    account, target = resources
    worker, task, control = control_for(settings, account, target)
    control.save_device(b'account-one-private-data')
    worker.queue.finish(task['id'], task['execution_id'], 'succeeded', 'done', 'Synthetic')
    second = admin.post('/api/v1/accounts', json={
        'username': 'second@example.com', 'password': 'synthetic-password',
        'route_type': 'direct', 'target_ids': [target],
    }).json()['id']
    worker2, task2, control2 = control_for(settings, second, target)
    assert control2.load_device() is None
    # Even a swapped database blob cannot authenticate under another account.
    with database(settings.db_path) as conn:
        blob = conn.execute('SELECT archive_cipher FROM browser_devices WHERE account_id=?', (account,)).fetchone()[0]
        conn.execute('INSERT INTO browser_devices VALUES(?,?,?)', (second, blob, time.time()))
    with pytest.raises(ValueError, match='encrypted browser device cannot be read'):
        control2.load_device()
    worker2.queue.finish(task2['id'], task2['execution_id'], 'failed', 'done', 'Synthetic')
    assert admin.delete(f'/api/v1/accounts/{second}').status_code == 200
    with database(settings.db_path) as conn:
        assert conn.execute('SELECT 1 FROM browser_devices WHERE account_id=?', (second,)).fetchone() is None


def test_timezone_persistence_keeps_identity_and_account_version(settings, resources):
    worker, task, control = control_for(settings, *resources)
    a, _, _ = worker.load(task)
    seed = a['_browser_profile']['identity_seed']
    version = a['version']
    control.update_timezone('America/Los_Angeles')
    after, _, _ = worker.load(task)
    assert after['_browser_profile']['identity_seed'] == seed
    assert after['_browser_profile']['context']['timezone_id'] == 'America/Los_Angeles'
    assert after['version'] == version
    with pytest.raises(ValueError):
        control.update_timezone('../invalid')


def as_version_two(settings):
    with database(settings.db_path) as conn:
        conn.execute('DROP TABLE browser_requests')
        conn.execute('DROP TABLE login_flows')
        conn.execute('DROP INDEX task_dependency')
        conn.execute('ALTER TABLE tasks DROP COLUMN depends_on_task_id')
        conn.execute('DROP TABLE browser_devices')
        conn.execute('PRAGMA user_version=2')


def test_v2_upgrade_and_restore_preserve_existing_identity_state(settings, resources, tmp_path):
    worker, task, control = control_for(settings, *resources)
    control.save_state({'cookies': [], 'origins': []})
    with database(settings.db_path) as conn:
        before = conn.execute('SELECT profile_cipher FROM browser_profiles').fetchone()[0]
    as_version_two(settings)
    source = tmp_path/'v2.db'
    with sqlite3.connect(settings.db_path) as origin, sqlite3.connect(source) as destination:
        origin.backup(destination)
        destination.execute('PRAGMA journal_mode=DELETE')
    with pytest.raises(RuntimeError, match='explicit migrate'):
        validate_database(settings.db_path, worker.key)
    migrate(settings.db_path, worker.key)
    validate_database(settings.db_path, worker.key)
    with database(settings.db_path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
        assert conn.execute('SELECT profile_cipher FROM browser_profiles').fetchone()[0] == before
        assert conn.execute('SELECT count(*) FROM browser_devices').fetchone()[0] == 0
    restored = replace(settings, db_path=tmp_path/'restored'/'db')
    restore(restored, source)
    validate_database(restored.db_path, worker.key)
    with database(restored.db_path) as conn:
        assert conn.execute('SELECT profile_cipher FROM browser_profiles').fetchone()[0] == before


def test_v2_wrong_key_does_not_add_device_table(settings, resources):
    as_version_two(settings)
    with pytest.raises(ValueError):
        migrate(settings.db_path, os.urandom(32))
    with database(settings.db_path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 2
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='browser_devices'").fetchone() is None
