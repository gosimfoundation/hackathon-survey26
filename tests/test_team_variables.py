"""Team variables and allowed domains in real PostgreSQL (migration 20261004040000)."""
import uuid

import psycopg
import pytest
from test_project_database import database, setup, session, identity, query, rpc  # noqa: F401

CIPHER = 'v1.' + 'A' * 16 + '.' + 'B' * 40 + '=='


def env(uri, user):
    return rpc(uri, 'observer_team_environment', role='authenticated', user=user)


def save(uri, user, name, *, secret=True, value=None, hint='wxyz', vid=None):
    rpc(uri, 'observer_save_team_variable', user, vid or uuid.uuid4(), name, secret,
        CIPHER if secret else None, None if secret else value, hint if secret else '')


def test_members_manage_variables_and_domains_without_reading_secrets(setup):
    s = setup; uri = s['uri']
    teammate, _ = identity(uri, team=s['team'])
    outsider, _ = identity(uri)
    assert env(uri, s['user'])['variables'] == [] and env(uri, s['user'])['domains'] == []
    save(uri, s['user'], 'KIMI_API_KEY')
    save(uri, s['user'], 'KIMI_MODEL', secret=False, value='k3')
    view = env(uri, teammate)
    assert [(v['name'], v['secret'], v['hint'], v['value']) for v in view['variables']] == [
        ('KIMI_API_KEY', True, 'wxyz', None), ('KIMI_MODEL', False, '', 'k3')]
    assert CIPHER not in str(view) and env(uri, outsider)['variables'] == []
    # Replacing keeps one row per name.
    save(uri, s['user'], 'KIMI_MODEL', secret=False, value='kimi-for-coding')
    assert [v['value'] for v in env(uri, s['user'])['variables'] if v['name'] == 'KIMI_MODEL'] == ['kimi-for-coding']
    # Rules: reserved names, bad names and both/neither values are refused.
    for name in ('OBSERVER_RUN_TOKEN', 'SAC_X', 'HTTPS_PROXY', 'FTP_PROXY', 'PATH', 'lower', '1X', 'A' * 65):
        with pytest.raises(psycopg.Error, match='invalid_team_variable'):
            save(uri, s['user'], name)
    with pytest.raises(psycopg.Error, match='invalid_team_variable'):
        rpc(uri, 'observer_save_team_variable', s['user'], uuid.uuid4(), 'X', True, CIPHER, 'plain', '')
    # Participants cannot write values directly or read the tables.
    with pytest.raises(psycopg.Error, match='permission denied'):
        rpc(uri, 'observer_save_team_variable', s['user'], uuid.uuid4(), 'X', False, None, 'v', '',
            role='authenticated', user=s['user'])
    for table in ('observer_team_variables', 'observer_team_domains'):
        with pytest.raises(psycopg.Error, match='permission denied'):
            query(uri, f'select * from private.{table}', role='authenticated', user=s['user'])
    # At most 20 variables.
    for i in range(18):
        save(uri, s['user'], f'V{i}', secret=False, value='x')
    with pytest.raises(psycopg.Error, match='team_variable_limit'):
        save(uri, s['user'], 'ONE_TOO_MANY', secret=False, value='x')
    assert rpc(uri, 'observer_delete_team_variable', 'V0', role='authenticated', user=teammate) is True
    assert rpc(uri, 'observer_delete_team_variable', 'KIMI_MODEL', role='authenticated', user=outsider) is False
    # Domains: public names only, at most ten, replaced as a set.
    assert rpc(uri, 'observer_set_team_domains', s['user'], ['api.kimi.com', 'api.deepseek.com']) == [
        'api.kimi.com', 'api.deepseek.com']
    assert env(uri, s['user'])['domains'] == ['api.deepseek.com', 'api.kimi.com']
    rpc(uri, 'observer_set_team_domains', s['user'], ['api.kimi.com'])
    assert env(uri, teammate)['domains'] == ['api.kimi.com']
    for bad in (['127.0.0.1'], ['localhost'], ['x.internal'], ['API.KIMI.COM'], ['api.kimi.com:443'],
                ['https://api.kimi.com'], ['a.com', 'a.com'], [f'd{i}.com' for i in range(11)], ['svc.local']):
        with pytest.raises(psycopg.Error, match='invalid_team_domains'):
            rpc(uri, 'observer_set_team_domains', s['user'], bad)


def test_scheduler_reads_a_runs_team_variables_and_domains(setup):
    s = setup; uri = s['uri']
    save(uri, s['user'], 'OPENAI_API_KEY')
    save(uri, s['user'], 'OPENAI_MODEL', secret=False, value='k3')
    rpc(uri, 'observer_set_team_domains', s['user'], ['api.kimi.com'])
    run, _, _ = session(s)
    egress = rpc(uri, 'observer_run_team_egress', run)
    assert egress['domains'] == ['api.kimi.com']
    assert [(v['name'], v['secret'], v['encrypted_value'], v['plain_value']) for v in egress['variables']] == [
        ('OPENAI_API_KEY', True, CIPHER, None), ('OPENAI_MODEL', False, None, 'k3')]
    with pytest.raises(psycopg.Error, match='permission denied'):
        rpc(uri, 'observer_run_team_egress', run, role='authenticated', user=s['user'])
    assert rpc(uri, 'observer_hardening')['team_egress'] is False


def test_backfill_turns_a_saved_model_api_into_variables_and_a_domain(setup):
    s = setup; uri = s['uri']
    provider = uuid.uuid4()
    rpc(uri, 'observer_save_team_model', s['user'], provider, 'https://api.kimi.com/coding/v1', 'k3', CIPHER, 'Qx2z',
        'anthropic')
    assert query(uri, 'select private.observer_backfill_team_variables()')[0][0] == 1
    rows = query(uri, '''select id,name,secret,encrypted_value,plain_value,hint from private.observer_team_variables
        where team_id=%s order by name''', (s['team'],))
    assert [(r[1], r[2], r[3], r[4], r[5]) for r in rows] == [
        ('ANTHROPIC_API_KEY', True, CIPHER, None, 'Qx2z'),
        ('ANTHROPIC_BASE_URL', False, None, 'https://api.kimi.com/coding/v1', ''),
        ('ANTHROPIC_MODEL', False, None, 'k3', '')]
    # The key keeps its ciphertext and the id it is bound to.
    assert rows[0][0] == provider
    assert env(uri, s['user'])['domains'] == ['api.kimi.com']
    # Idempotent: a team that already has variables is left alone.
    assert query(uri, 'select private.observer_backfill_team_variables()')[0][0] == 0


def test_relay_teams_are_told_to_enter_their_key(setup):
    s = setup; uri = s['uri']
    rpc(uri, 'observer_set_team_model_mode', 'relay', role='authenticated', user=s['user'])
    assert env(uri, s['user'])['relay_key_missing'] is True
    save(uri, s['user'], 'OPENAI_API_KEY')
    assert env(uri, s['user'])['relay_key_missing'] is False
