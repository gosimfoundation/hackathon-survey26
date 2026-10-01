"""Recorded runner placement across up to thirty-six organizations."""
from __future__ import annotations

import concurrent.futures
import secrets
import uuid

import psycopg
import pytest

from test_project_database import database, identity, query, rpc, session, setup  # noqa: F401

ORG = 'AGENTIC-OBSERVER26-runner-'


def install(uri, n, enabled=True):
    query(uri, """insert into private.observer_installations
        (organization,organization_id,installation_id,repository_id,approved_sha,enabled)
        values(%s,%s,%s,%s,%s,%s) on conflict(organization) do update set enabled=excluded.enabled""",
          (ORG + str(n), str(1000 + n), 2000 + n, str(3000 + n), 'a' * 40, enabled))


def test_organization_names_one_to_thirtysix_only(setup):
    uri = setup['uri']
    for n in (1, 7, 10, 12, 13, 29, 30, 36):
        install(uri, n, enabled=False)
    for name in ('37', '0', '01', '1x'):
        with pytest.raises(psycopg.Error, match='organization_check'):
            query(uri, """insert into private.observer_installations
                (organization,organization_id,installation_id,repository_id,approved_sha)
                values(%s,'9','9','9',%s)""", (ORG + name, 'a' * 40))
    check = query(uri, """select pg_get_constraintdef(oid) from pg_constraint
        where conname='observer_materializations_archive_ref_check'""")[0][0]
    assert '[12][0-9]|3[0-6]' in check


def test_existing_participant_keeps_the_organization_of_their_jobs(setup):
    s = setup; uri = s['uri']
    for n in range(1, 13):
        install(uri, n)
    # A job placed before this change stays authoritative for its owner.
    run, _, _ = session(s)
    rpc(uri, 'observer_enqueue_job', uuid.uuid4(), 'engine', run, None, ORG + '5',
        secrets.token_urlsafe(32), 'encrypted job payload', 'encrypted nonce')
    query(uri, 'delete from private.observer_placements where user_id=%s', (s['user'],))
    assert rpc(uri, 'observer_placement', s['user']) == ORG + '5'
    assert rpc(uri, 'observer_placement', s['user']) == ORG + '5'
    assert query(uri, 'select organization from private.observer_placements where user_id=%s',
                 (s['user'],)) == [(ORG + '5',)]


def test_new_participants_fill_the_least_loaded_enabled_organizations(setup):
    s = setup; uri = s['uri']
    query(uri, 'delete from private.observer_placements')
    for n in range(1, 7):
        install(uri, n)
    for n in range(7, 13):
        install(uri, n, enabled=False)
    for n in range(1, 7):
        user, _ = identity(uri)
        query(uri, 'insert into private.observer_placements(user_id,organization) values(%s,%s)', (user, ORG + str(n)))
    # Disabled organizations are never chosen.
    user, _ = identity(uri)
    assert rpc(uri, 'observer_placement', user) == ORG + '1'
    for n in range(7, 13):
        install(uri, n)
    placed = []
    for _ in range(6):
        user, _ = identity(uri)
        placed.append(rpc(uri, 'observer_placement', user))
    assert placed == [ORG + str(n) for n in range(7, 13)]
    # A recorded placement survives its organization being disabled later.
    install(uri, 7, enabled=False)
    first = query(uri, 'select user_id from private.observer_placements where organization=%s', (ORG + '7',))[0][0]
    assert rpc(uri, 'observer_placement', first) == ORG + '7'


def test_concurrent_first_placement_is_recorded_once(setup):
    s = setup; uri = s['uri']
    for n in range(1, 13):
        install(uri, n)
    user, _ = identity(uri)
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = set(pool.map(lambda _: rpc(uri, 'observer_placement', user), range(8)))
    assert len(results) == 1
    assert query(uri, 'select count(*) from private.observer_placements where user_id=%s', (user,)) == [(1,)]


def test_no_enabled_runner_and_participant_access_are_refused(setup):
    s = setup; uri = s['uri']
    query(uri, 'update private.observer_installations set enabled=false')
    user, _ = identity(uri)
    with pytest.raises(psycopg.Error, match='runner_not_configured'):
        rpc(uri, 'observer_placement', user)
    for role in ('authenticated', 'anon'):
        with pytest.raises(psycopg.Error, match='permission denied'):
            rpc(uri, 'observer_placement', user, role=role, user=user)
        with pytest.raises(psycopg.Error, match='permission denied'):
            query(uri, 'select * from private.observer_placements', role=role, user=user)
