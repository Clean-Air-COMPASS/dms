import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.main import app
from models import Event, PasswordResetToken, Passkey, RefreshToken, User
from services.auth import create_access_token, get_auth_settings, hash_password, scopes_from_roles, verify_password
from services.email_configuration import get_or_create_email_settings
from services.email_delivery import EmailService
from test_setup_state import isolated_setup_database  # noqa: F401

OLD = "OriginalCredential123!"
NEW = "ReplacementCredential456!"


@pytest.fixture()
def recovery(isolated_setup_database, monkeypatch):
    _, _, factory = isolated_setup_database
    monkeypatch.setenv("COMPASSAQ_APPLICATION_URL", "https://compass.example.org")
    admin_id, user_id, org_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with factory() as session:
        for uid, email in [(admin_id, 'admin@example.org'), (user_id, 'staff@example.org')]:
            session.add(User(user_id=uid, org_id=org_id, email=email, password_hash=hash_password(OLD), is_active=True))
        session.commit()
    jwt, _ = create_access_token(settings=get_auth_settings(), user_id=admin_id, org_id=org_id, roles=['admin'], scopes=scopes_from_roles(['admin']))
    client = TestClient(app)
    client.headers['authorization'] = f'Bearer {jwt}'
    return client, user_id, factory, admin_id, org_id


def create(recovery):
    client, uid, *_ = recovery
    response = client.post(f'/admin/users/{uid}/password-reset-link', headers={'host': 'evil.example', 'x-forwarded-host': 'evil.example'})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    assert data['expires_in_minutes'] == 60
    assert data['reset_url'].startswith('https://compass.example.org/reset-password#token=')
    return parse_qs(urlsplit(data['reset_url']).fragment)['token'][0]


def test_complete_reset_security_and_one_time_use(recovery):
    client, uid, factory, *_ = recovery
    now = datetime.now(timezone.utc)
    with factory() as session:
        user = session.get(User, uid)
        user.failed_login_count = 5
        user.last_failed_at = now
        user.locked_until = now + timedelta(minutes=15)
        session.add(Passkey(credential_id='preserved', user_id=uid, public_key='public', sign_count=7, rp_id='compass.example.org'))
        session.add(RefreshToken(refresh_token_id=uuid.uuid4(), user_id=uid, token_hash='refresh-hash', issued_at=now, expires_at=now + timedelta(days=10)))
        session.commit()
    raw = create(recovery)
    with factory() as session:
        saved = session.scalar(select(PasswordResetToken))
        assert saved.token_hash == hashlib.sha256(raw.encode()).hexdigest()
        assert raw not in str(saved.__dict__)
    assert client.post('/auth/password-reset/verify', json={'token': raw}).json()['valid']
    client.headers.pop('authorization')
    result = client.post('/auth/password-reset/complete', json={'token': raw, 'password': NEW})
    assert result.status_code == 200, result.text
    assert client.post('/auth/password-reset/complete', json={'token': raw, 'password': OLD}).json()['detail'] == 'reset_used'
    with factory() as session:
        user = session.get(User, uid)
        assert verify_password(NEW, user.password_hash)
        assert not verify_password(OLD, user.password_hash)
        assert user.failed_login_count == 0 and user.locked_until is None and user.last_failed_at is None
        assert session.scalar(select(RefreshToken)).revoked_at is not None
        assert session.get(Passkey, 'preserved').sign_count == 7
        events = session.scalars(select(Event).where(Event.source == 'password_reset')).all()
        assert {e.event_type for e in events} == {'password_reset_link_created', 'password_reset_completed'}
        for event in events:
            assert raw not in str(event.__dict__)
            assert NEW not in str(event.__dict__)
            assert event.params['target_user_id'] == str(uid)
    assert client.post('/auth/login', json={'email': 'staff@example.org', 'password': OLD}).status_code == 401
    assert client.post('/auth/login', json={'email': 'staff@example.org', 'password': NEW}).status_code == 200


def test_replacement_expiration_policy_and_invalid_input(recovery):
    client, uid, factory, *_ = recovery
    old = create(recovery)
    raw = create(recovery)
    assert raw != old and len(raw) == 43
    assert client.post('/auth/password-reset/verify', json={'token': old}).json()['detail'] == 'reset_used'
    for password in ['short', 'staff-is-in-this-password', 'staff@example.org-password']:
        result = client.post('/auth/password-reset/complete', json={'token': raw, 'password': password})
        assert result.json()['detail'] == 'password_policy'
        assert password not in result.text
    with factory() as session:
        token = session.get(PasswordResetToken, hashlib.sha256(raw.encode()).hexdigest())
        token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    for endpoint in ['verify', 'complete']:
        assert client.post(f'/auth/password-reset/{endpoint}', json={'token': raw, 'password': NEW}).json()['detail'] == 'reset_expired'
    for payload in [{'token': {'secret': raw}}, {'token': 'invalid'}, {}]:
        response = client.post('/auth/password-reset/verify', json=payload)
        assert response.status_code == 400 and raw not in response.text
    assert client.post(f'/admin/users/{uuid.uuid4()}/password-reset-link').status_code == 404


@pytest.mark.parametrize('role', ['viewer', 'analyst'])
def test_non_admin_and_anonymous_cannot_issue_or_send(recovery, role, monkeypatch):
    client, uid, _, _, org = recovery
    monkeypatch.delenv('COMPASSAQ_APPLICATION_URL')
    client.headers['origin'] = 'http://testserver'
    token, _ = create_access_token(settings=get_auth_settings(), user_id=uid, org_id=org, roles=[role], scopes=scopes_from_roles([role]))
    client.headers['authorization'] = f'Bearer {token}'
    for action in ['link', 'email']:
        assert client.post(f'/admin/users/{uid}/password-reset-{action}').status_code == 403
    client.headers.pop('authorization')
    assert client.post(f'/admin/users/{uid}/password-reset-link').status_code == 401


@pytest.mark.parametrize('target_admin', [False, True])
def test_disabled_accounts_and_administrators_can_reset_without_reactivation(recovery, target_admin):
    client, uid, factory, admin_id, _ = recovery
    target = admin_id if target_admin else uid
    raw = create((client, target, factory))
    with factory() as session:
        session.get(User, target).is_active = False
        session.commit()
    assert client.post('/auth/password-reset/complete', json={'token': raw, 'password': NEW}).status_code == 200
    with factory() as session:
        assert session.get(User, target).is_active is False


def ready_email(factory):
    with factory() as session:
        settings = get_or_create_email_settings(session)
        settings.enabled = True
        settings.smtp_host = 'localhost'
        settings.smtp_port = 2525
        settings.smtp_security_mode = 'none'
        settings.from_email = 'compass@example.org'
        settings.administrator_recipients = ['admin@example.org']
        settings.last_test_status = 'success'
        settings.last_tested_at = datetime.now(timezone.utc)
        session.commit()


def test_smtp_readiness_is_authoritative_and_manual_link_independent(recovery):
    client, uid, factory, *_ = recovery
    assert client.get('/admin/users/password-reset/readiness').json()['email_delivery_ready'] is False
    assert client.post(f'/admin/users/{uid}/password-reset-email').status_code == 409
    create(recovery)
    ready_email(factory)
    with factory() as session:
        settings = get_or_create_email_settings(session)
        settings.last_test_status = None
        settings.last_tested_at = None
        session.commit()
    assert client.post(f'/admin/users/{uid}/password-reset-email').status_code == 409
    create(recovery)


@pytest.mark.parametrize('fail', [False, True])
@pytest.mark.parametrize('language', ['en', 'es'])
def test_existing_email_transport_success_and_failure(recovery, monkeypatch, fail, language):
    client, uid, factory, *_ = recovery
    ready_email(factory)
    with factory() as session:
        session.get(User, uid).preferred_language_code = language
        session.commit()
    messages = []
    def send(self, **message):
        messages.append(message)
        if fail:
            raise RuntimeError('SMTP SECRET ' + message['text_body'])
    monkeypatch.setattr(EmailService, 'send', send)
    previous = create(recovery)
    response = client.post(f'/admin/users/{uid}/password-reset-email')
    assert response.status_code == (502 if fail else 200)
    assert 'SMTP SECRET' not in response.text
    assert len(messages) == 1 and messages[0]['recipients'] == ['staff@example.org']
    assert '60' in messages[0]['text_body']
    assert ('administrador' if language == 'es' else 'administrator') in messages[0]['text_body']
    assert 'staff@example.org' not in messages[0]['text_body']
    assert client.post('/auth/password-reset/verify', json={'token': previous}).status_code == 400
    with factory() as session:
        tokens = session.scalars(select(PasswordResetToken)).all()
        assert sum(t.consumed_at is None for t in tokens) == (0 if fail else 1)
        events = session.scalars(select(Event).where(Event.source == 'password_reset')).all()
        assert ('password_reset_email_failed' if fail else 'password_reset_email_sent') in [e.event_type for e in events]
        assert '#token=' not in str([e.__dict__ for e in events])


@pytest.mark.parametrize('origin', ['https://user:secret@example.org', 'https://example.org/path', 'https://example.org?host=evil', 'javascript:alert(1)', 'https://example.org:invalid'])
def test_invalid_trusted_origins_are_rejected_without_persisting_tokens(recovery, monkeypatch, origin):
    client, uid, factory, *_ = recovery
    monkeypatch.setenv('COMPASSAQ_APPLICATION_URL', origin)
    response = client.post(f'/admin/users/{uid}/password-reset-link', headers={'origin': 'http://testserver'})
    assert response.status_code == 503
    with factory() as session:
        assert session.scalar(select(PasswordResetToken)) is None


def test_production_requires_https(recovery, monkeypatch):
    client, uid, *_ = recovery
    monkeypatch.setenv('COMPASSAQ_ENV', 'production')
    monkeypatch.setenv('COMPASSAQ_APPLICATION_URL', 'http://compass.example.org')
    assert client.post(f'/admin/users/{uid}/password-reset-link').status_code == 503


def test_user_detail_unlock_and_deleted_target(recovery):
    client, uid, factory, *_ = recovery
    with factory() as session:
        user = session.get(User, uid)
        user.failed_login_count = 3
        user.last_failed_at = datetime.now(timezone.utc)
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
        session.commit()
    detail = client.get(f'/admin/users/{uid}').json()
    assert detail['failed_login_count'] == 3 and detail['locked_until']
    unlocked = client.post(f'/admin/users/{uid}/unlock')
    assert unlocked.status_code == 200
    assert unlocked.json()['failed_login_count'] == 0 and unlocked.json()['locked_until'] is None
    raw = create(recovery)
    assert client.delete(f'/admin/users/{uid}').status_code == 204
    assert client.post(f'/admin/users/{uid}/password-reset-link').status_code == 404
    assert client.post('/auth/password-reset/complete', json={'token': raw, 'password': NEW}).status_code == 400


@pytest.mark.parametrize('origin', [
    'http://localhost', 'http://localhost:8080', 'http://192.168.1.50:8080',
    'http://[::1]:8080', 'http://air.internal:8080', 'https://air.example.org:9443',
])
@pytest.mark.parametrize('setting', [None, ''])
def test_same_origin_link_needs_no_application_url(recovery, monkeypatch, origin, setting):
    client, uid, *_ = recovery
    if setting is None:
        monkeypatch.delenv('COMPASSAQ_APPLICATION_URL')
    else:
        monkeypatch.setenv('COMPASSAQ_APPLICATION_URL', setting)
    # This TestClient version cannot parse IPv6 destinations. The explicit Host
    # supplies the real ASGI authority while its transport uses a simple name.
    parsed = urlsplit(origin)
    response = client.post(f'{parsed.scheme}://testserver/admin/users/{uid}/password-reset-link', headers={
        'origin': origin, 'host': parsed.netloc,
    })
    assert response.status_code == 200, response.text
    assert response.json()['reset_url'].startswith(f'{origin}/reset-password#token=')


@pytest.mark.parametrize('headers', [
    {}, {'origin': 'null'}, {'origin': 'https://evil.example'},
    {'origin': 'http://testserver', 'host': 'evil.example'},
    {'origin': 'http://testserver:8080'},
    {'origin': 'https://testserver', 'x-forwarded-proto': 'https'},
    {'origin': 'https://evil.example', 'x-forwarded-host': 'evil.example', 'x-forwarded-proto': 'https'},
    {'origin': 'http://testserver', 'sec-fetch-site': 'cross-site'},
    {'origin': 'http://testserver', 'sec-fetch-site': 'same-site'},
    {'origin': 'http://testserver/path', 'host': 'testserver/path'},
    {'origin': 'http://testserver/', 'host': 'testserver/'},
    {'origin': 'http://@testserver', 'host': '@testserver'},
    {'origin': 'http://name:secret@testserver', 'host': 'name:secret@testserver'},
    [('origin', 'http://testserver'), ('origin', 'http://evil.example')],
    [('origin', 'http://testserver'), ('host', 'testserver'), ('host', 'evil.example')],
])
@pytest.mark.parametrize('action', ['link', 'email'])
def test_origin_poisoning_is_rejected_before_issuing_or_sending(recovery, monkeypatch, headers, action):
    client, uid, factory, *_ = recovery
    monkeypatch.delenv('COMPASSAQ_APPLICATION_URL')
    ready_email(factory)
    send = []
    monkeypatch.setattr(EmailService, 'send', lambda self, **message: send.append(message))
    response = client.post(f'/admin/users/{uid}/password-reset-{action}', headers=headers)
    assert response.status_code == 400, response.text
    assert response.json()['detail'] == 'reset_origin_invalid'
    assert send == []
    with factory() as session:
        assert session.scalar(select(PasswordResetToken)) is None


def test_forwarded_headers_cannot_override_valid_browser_origin(recovery, monkeypatch):
    client, uid, *_ = recovery
    monkeypatch.delenv('COMPASSAQ_APPLICATION_URL')
    response = client.post(f'/admin/users/{uid}/password-reset-link', headers={
        'origin': 'http://testserver', 'sec-fetch-site': 'same-origin',
        'x-forwarded-host': 'evil.example', 'x-forwarded-proto': 'https',
        'forwarded': 'host=evil.example;proto=https',
    })
    assert response.status_code == 200
    assert response.json()['reset_url'].startswith('http://testserver/reset-password#token=')


def test_same_origin_email_needs_no_application_url(recovery, monkeypatch):
    client, uid, factory, *_ = recovery
    monkeypatch.delenv('COMPASSAQ_APPLICATION_URL')
    ready_email(factory)
    messages = []
    monkeypatch.setattr(EmailService, 'send', lambda self, **message: messages.append(message))
    response = client.post(f'http://localhost:8080/admin/users/{uid}/password-reset-email', headers={'origin': 'http://localhost:8080'})
    assert response.status_code == 200, response.text
    assert 'http://localhost:8080/reset-password#token=' in messages[0]['text_body']


def test_optional_override_remains_authoritative_for_custom_proxy(recovery, monkeypatch):
    client, uid, *_ = recovery
    monkeypatch.setenv('COMPASSAQ_APPLICATION_URL', 'https://air.example.org:9443/')
    response = client.post(f'/admin/users/{uid}/password-reset-link', headers={
        'host': 'internal-api:8000', 'origin': 'https://air.example.org:9443',
        'x-forwarded-host': 'evil.example',
    })
    assert response.status_code == 200
    assert response.json()['reset_url'].startswith('https://air.example.org:9443/reset-password#token=')
