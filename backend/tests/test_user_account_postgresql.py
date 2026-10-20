"""Real PostgreSQL migration, uniqueness, proof and session concurrency."""
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from api.auth_deps import CurrentUser
from api.routes.account import EmailChange, change_email
from api.routes.auth import refresh_token
from models import Event, Passkey, RefreshToken, User
from postgresql_test_support import POSTGRES_TEST_URL_ENV, temporary_postgres_database, upgrade, downgrade
from services.account_security import consume_reauthentication, invalidate_account_sessions, issue_reauthentication, locked_account
from services.auth import generate_refresh_token, get_auth_settings, hash_password
from services.event_log import add_event

pytestmark = pytest.mark.skipif(not os.environ.get(POSTGRES_TEST_URL_ENV), reason=f'Set {POSTGRES_TEST_URL_ENV}')


def current(uid, org):
    return CurrentUser(user_id=uid, org_id=org, email='person@example.com', roles=['viewer'], scopes=[],
                       token_jti=uuid.uuid4(), token_exp=datetime.now(timezone.utc) + timedelta(minutes=15))


def request(cookie=None):
    headers = [(b'cookie', f'refresh_token={cookie}'.encode())] if cookie else []
    return Request({'type': 'http', 'method': 'POST', 'scheme': 'http', 'path': '/auth/refresh',
                    'headers': headers, 'server': ('localhost', 80), 'client': ('127.0.0.1', 1234), 'query_string': b''})


@pytest.fixture()
def postgres_account():
    with temporary_postgres_database('account') as (url, engine):
        upgrade(url, 'head')
        uid, org = uuid.uuid4(), uuid.uuid4()
        with Session(engine) as session:
            session.add(User(user_id=uid, org_id=org, email='person@example.com', password_hash=hash_password('OriginalCredential123!')))
            session.commit()
        yield url, engine, uid, org


def test_upgrade_existing_null_names_passkeys_audit_and_downgrade():
    with temporary_postgres_database('account_migration') as (url, engine):
        upgrade(url, '20260906_0023')
        uid, org = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(text('INSERT INTO "user" (user_id, org_id, email, password_hash) VALUES (:uid, :org, :email, :password)'),
                               {'uid': uid, 'org': org, 'email': 'legacy@example.com', 'password': hash_password('OriginalCredential123!')})
            connection.execute(text("INSERT INTO passkey (credential_id, user_id, public_key, sign_count, rp_id) VALUES ('legacy', :uid, 'test-key', 1, 'localhost')"), {'uid': uid})
        upgrade(url, 'head')
        with Session(engine) as session:
            user = session.get(User, uid)
            assert user.first_name is None and user.last_name is None and user.display_name == user.email
            key = session.get(Passkey, 'legacy')
            assert key.user_id == uid and key.created_at is None and key.last_used_at is None and key.name is None
            user.first_name, user.last_name = '李', 'García'
            add_event(session, event_type='profile_updated', source='test', actor_user_id=uid, actor_email=user.email)
            session.commit()
            session.delete(user)
            session.commit()
            event = session.scalar(select(Event).where(Event.source == 'test'))
            assert event.actor_user_id is None  # Existing ON DELETE SET NULL policy.
            assert event.actor_email == 'legacy@example.com' and event.actor_display_name == '李 García'
        downgrade(url, '20260906_0023')
        assert 'first_name' not in {c['name'] for c in inspect(engine).get_columns('user')}
        assert 'reauthentication_grant' not in inspect(engine).get_table_names()
        upgrade(url, 'head')


def test_one_proof_cannot_commit_two_concurrent_changes(postgres_account):
    _, engine, uid, org = postgres_account
    actor = current(uid, org)
    with Session(engine) as session:
        raw = issue_reauthentication(session, session.get(User, uid), actor)['reauthentication_token']
    barrier = threading.Barrier(2)

    def consume():
        with Session(engine) as session:
            barrier.wait(timeout=10)
            user = locked_account(session, uid)
            try:
                consume_reauthentication(session, user, actor, raw)
                session.commit()
                return 'success'
            except HTTPException as exc:
                session.rollback()
                return exc.detail['error_code']
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: consume(), range(2))) == ['reauthentication_required', 'success']


def test_concurrent_email_claims_return_conflict_without_losing_accounts(postgres_account):
    _, engine, uid, org = postgres_account
    other_uid = uuid.uuid4()
    with Session(engine) as session:
        session.add(User(user_id=other_uid, org_id=org, email='other@example.com', password_hash=hash_password('OriginalCredential123!')))
        session.commit()
    proofs = []
    for user_id in (uid, other_uid):
        actor = current(user_id, org)
        with Session(engine) as session:
            raw = issue_reauthentication(session, session.get(User, user_id), actor)['reauthentication_token']
        proofs.append((actor, raw))
    barrier = threading.Barrier(2)

    def claim(item):
        actor, raw = item
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                change_email(EmailChange(email=' SAME@example.com ', reauthentication_token=raw), request(), Response(), actor, session)
                return 200
            except HTTPException as exc:
                session.rollback()
                assert exc.detail == {'error_code': 'email_already_in_use'}
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, proofs)) == [200, 409]
    with Session(engine) as session:
        assert len(session.scalars(select(User)).all()) == 2
        assert len(session.scalars(select(User).where(User.email == 'same@example.com')).all()) == 1


def test_refresh_waits_for_sensitive_change_and_cannot_escape_revocation(postgres_account):
    _, engine, uid, _ = postgres_account
    raw, digest, token_id, issued, expires = generate_refresh_token(get_auth_settings())
    with Session(engine) as session:
        session.add(RefreshToken(refresh_token_id=token_id, user_id=uid, token_hash=digest, issued_at=issued, expires_at=expires))
        session.commit()
    started = threading.Event()

    def refresh():
        with Session(engine) as session:
            started.set()
            try:
                refresh_token(request(raw), Response(), session)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with Session(engine) as session, ThreadPoolExecutor(max_workers=1) as pool:
        user = locked_account(session, uid)
        pending = pool.submit(refresh)
        try:
            assert started.wait(timeout=10)
            # Observe an actual PostgreSQL lock wait before revoking. Merely
            # starting a thread can accidentally test sequential requests.
            deadline = time.monotonic() + 5
            blocked = False
            while time.monotonic() < deadline:
                with engine.connect() as observer:
                    blocked = observer.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE datname = current_database() AND cardinality(pg_blocking_pids(pid)) > 0)"
                    ))
                if blocked:
                    break
                time.sleep(0.02)
            assert blocked
            invalidate_account_sessions(session, user)
            session.commit()
        finally:
            session.rollback()  # Release the lock even if an assertion fails.
        assert pending.result(timeout=10) == 401
    with Session(engine) as session:
        assert len(session.scalars(select(RefreshToken)).all()) == 1


def test_concurrent_refresh_rotates_only_once(postgres_account):
    _, engine, uid, _ = postgres_account
    raw, digest, token_id, issued, expires = generate_refresh_token(get_auth_settings())
    with Session(engine) as session:
        session.add(RefreshToken(refresh_token_id=token_id, user_id=uid, token_hash=digest, issued_at=issued, expires_at=expires))
        session.commit()
    barrier = threading.Barrier(2)

    def refresh():
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                refresh_token(request(raw), Response(), session)
                return 200
            except HTTPException as exc:
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: refresh(), range(2))) == [200, 401]
