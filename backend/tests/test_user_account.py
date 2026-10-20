"""Account contract and security tests using real password and WebAuthn proofs."""
import time
import uuid

import pytest
from sqlalchemy import select

from models import Event, Passkey, ReauthenticationGrant, RefreshToken, Role, User
from services.auth import create_access_token, decode_access_token, get_auth_settings, hash_password, scopes_from_roles
from services.event_log import add_event
from services.user_identity import display_name
from test_setup_state import isolated_setup_database  # noqa: F401
from test_passkeys import Authenticator, PASSWORD, enrolled_client, enroll, options  # noqa: F401


def proof(client, password=PASSWORD):
    response = client.post('/auth/reauthenticate', json={'current_password': password})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()['reauthentication_token']


def token_for(user_id, factory, roles=('viewer',)):
    with factory() as session:
        user = session.get(User, user_id)
        token, _ = create_access_token(settings=get_auth_settings(), user_id=user.user_id,
                                      org_id=user.org_id, roles=list(roles), scopes=scopes_from_roles(roles))
    return f'Bearer {token}'


@pytest.mark.parametrize('first,last,expected', [
    ('Jennifer', 'DeWinter', 'Jennifer DeWinter'), ('Jennifer', None, 'Jennifer'),
    (None, 'DeWinter', 'DeWinter'), (None, None, 'person@example.com'),
    ('李', '秀英', '李 秀英'),
])
def test_display_name_rule(first, last, expected):
    assert display_name(first, last, 'person@example.com') == expected


def test_admin_profile_reuses_identity_rules_preserves_security_and_audits(enrolled_client):
    client, actor_id, factory = enrolled_client
    with factory() as session:
        session.add(Role(role_id=uuid.uuid4(), name='viewer'))
        session.commit()
    client.patch('/auth/me', json={'first_name': 'Review', 'last_name': 'Administrator'})
    created = client.post('/admin/users', json={
        'email': 'profile-target@example.org', 'password': PASSWORD, 'roles': ['viewer'],
    })
    assert created.status_code == 201, created.text
    target_id = created.json()['user_id']
    path = f'/admin/users/{target_id}'
    with factory() as session:
        target = session.get(User, uuid.UUID(target_id))
        password_hash = target.password_hash
        target.failed_login_count = 3
        session.commit()
    for payload, expected in [
        ({'first_name': '  María  ', 'last_name': ' 李 '}, ('María', '李', 'María 李')),
        ({'first_name': '  '}, (None, '李', '李')),
        ({'last_name': None}, (None, None, 'profile-target@example.org')),
    ]:
        response = client.put(path, json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert tuple(result[key] for key in ('first_name', 'last_name', 'display_name')) == expected
        assert result['roles'] == ['viewer'] and result['is_active'] is True
        assert result['failed_login_count'] == 3
        listed = next(user for user in client.get('/admin/users').json() if user['user_id'] == target_id)
        assert listed['display_name'] == expected[2]
    for field in ('first_name', 'last_name'):
        assert client.put(path, json={field: 'x' * 100}).status_code == 200
        rejected = client.put(path, json={field: 'x' * 101})
        self_service = client.patch('/auth/me', json={field: 'x' * 101})
        assert rejected.status_code == self_service.status_code == 422
        assert rejected.json()['detail']['error_code'] == self_service.json()['detail']['error_code'] == 'invalid_name_length'
    with factory() as session:
        assert session.get(User, uuid.UUID(target_id)).password_hash == password_hash
        events = session.scalars(select(Event).where(Event.source == 'admin.users', Event.event_type == 'profile_updated')).all()
        assert len(events) == 5
        assert all(event.actor_user_id == actor_id and event.actor_display_name == 'Review Administrator' for event in events)
        assert events[0].params == {'target_user_id': target_id, 'changed_fields': ['first_name', 'last_name']}
        assert all(set(event.params) == {'target_user_id', 'changed_fields'} for event in events)
    # An unchanged profile must not create an extra change event.
    assert client.put(path, json={'last_name': 'x' * 100}).status_code == 200
    with factory() as session:
        assert len(session.scalars(select(Event).where(Event.source == 'admin.users')).all()) == 5
    client.headers['authorization'] = token_for(uuid.UUID(target_id), factory)
    assert client.put(path, json={'first_name': 'Unauthorized'}).status_code == 403
    assert client.put(f'/admin/users/{actor_id}', json={'first_name': 'Unauthorized'}).status_code == 403


def test_profile_names_unicode_partial_null_and_read_only_fields(enrolled_client):
    client, uid, factory = enrolled_client
    client.headers['authorization'] = token_for(uid, factory)
    initial = client.get('/auth/me').json()
    assert initial['first_name'] is None and initial['last_name'] is None
    assert initial['display_name'] == initial['email'] and initial['passkey_count'] == 0
    for payload, expected in [
        ({'first_name': '  李  '}, ('李', None, '李')),
        ({'last_name': '  García  '}, ('李', 'García', '李 García')),
        ({'first_name': ' \t\n '}, (None, 'García', 'García')),
        ({'last_name': None}, (None, None, initial['email'])),
    ]:
        response = client.patch('/auth/me', json=payload)
        assert response.status_code == 200, response.text
        assert tuple(response.json()[field] for field in ('first_name', 'last_name', 'display_name')) == expected
    for field, value in [('roles', ['admin']), ('scopes', ['users:write']), ('is_active', False),
                         ('email', 'bad@example.com'), ('user_id', str(uuid.uuid4())), ('preferred_language_code', 'es')]:
        assert client.patch('/auth/me', json={field: value}).status_code == 422
    too_long = client.patch('/auth/me', json={'first_name': 'x' * 101})
    assert too_long.json()['detail']['error_code'] == 'invalid_name_length'
    assert client.get('/admin/users').status_code == 403
    assert client.patch('/auth/me/preferences', json={'preferred_language_code': 'es'}).json()['preferred_language_code'] == 'es'
    assert client.patch('/auth/me', json={'first_name': 'Jennifer'}).json()['preferred_language_code'] == 'es'
    with factory() as session:
        event = session.scalars(select(Event).where(Event.event_type == 'profile_updated').order_by(Event.event_id.desc())).first()
        assert event.actor_user_id == uid and event.actor_display_name == 'Jennifer'


def test_email_change_preserves_identity_passkeys_and_replaces_refresh_sessions(enrolled_client):
    client, uid, factory = enrolled_client
    authenticator = Authenticator()
    enroll(client, authenticator)
    initial = client.get('/auth/me').json()
    other_login = client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD})
    old_refresh = other_login.cookies['refresh_token']
    grant = proof(client)
    result = client.post('/auth/me/email', json={'email': '  New.Login@EXAMPLE.COM  ', 'reauthentication_token': grant})
    assert result.status_code == 200, result.text
    assert 'HttpOnly' in result.headers['set-cookie']
    claims = decode_access_token(result.json()['access_token'], get_auth_settings())
    assert claims['sub'] == str(uid) and 'email' not in claims
    # Even the old bearer token resolves the current email from the account.
    current = client.get('/auth/me').json()
    assert current['email'] == 'new.login@example.com'
    assert current['user_id'] == initial['user_id'] and current['roles'] == initial['roles']
    with factory() as session:
        tokens = session.scalars(select(RefreshToken).where(RefreshToken.user_id == uid)).all()
        assert sum(t.revoked_at is None for t in tokens) == 1
        assert session.scalar(select(Passkey)).user_id == uid
        assert session.get(User, uid).is_active
        event = session.scalar(select(Event).where(Event.event_type == 'email_changed'))
        assert event.actor_user_id == uid and event.actor_email == current['email']
        assert event.params == {'previous_email': 'passkey@example.com'}
    client.cookies.set('refresh_token', old_refresh, path='/auth')
    assert client.post('/auth/refresh').status_code == 401
    client.cookies.set('refresh_token', result.cookies['refresh_token'], path='/auth')
    assert client.post('/auth/refresh').status_code == 200
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD}).status_code == 401
    assert client.post('/auth/login', json={'email': ' NEW.LOGIN@example.com ', 'password': PASSWORD}).status_code == 200
    opts = options(client, 'login')
    signed_in = client.post('/auth/passkeys/login/verify', json=authenticator.response(opts, register=False, user_id=uid, count=2))
    assert signed_in.status_code == 200, signed_in.text
    assert decode_access_token(signed_in.json()['access_token'], get_auth_settings())['sub'] == str(uid)


def test_email_errors_and_sanitization(enrolled_client):
    client, _, _ = enrolled_client
    created = client.post('/admin/users', json={'email': 'other@example.com', 'password': PASSWORD})
    assert created.status_code == 201, created.text
    assert client.post('/auth/me/email', json={'email': 'new@example.com'}).json()['detail']['error_code'] == 'reauthentication_required'
    grant = proof(client)
    duplicate = client.post('/auth/me/email', json={'email': ' OTHER@example.com ', 'reauthentication_token': grant})
    assert duplicate.status_code == 409 and duplicate.json()['detail']['error_code'] == 'email_already_in_use'
    invalid = client.post('/auth/me/email', json={'email': 'not-an-email', 'reauthentication_token': grant})
    assert invalid.status_code == 422 and invalid.json()['detail']['error_code'] == 'invalid_email'
    for path, payload in [('/auth/reauthenticate', {'current_password': ['SECRET']}),
                          ('/auth/me/password', {'password': ['SECRET'], 'confirm_password': 'SECRET'}),
                          ('/auth/me/email', {'email': [], 'reauthentication_token': 'SECRET'})]:
        response = client.post(path, json=payload)
        assert response.status_code == 422 and 'SECRET' not in response.text


def test_password_change_policy_confirmation_and_preservation(enrolled_client):
    client, uid, factory = enrolled_client
    enroll(client, Authenticator())
    wrong = client.post('/auth/reauthenticate', json={'current_password': 'wrong'})
    assert wrong.status_code == 403 and wrong.json()['detail']['error_code'] == 'incorrect_current_password'
    grant = proof(client)
    for password, confirmation, code in [('short', 'short', 'password_policy'),
                                          ('passkey-long-password', 'passkey-long-password', 'password_policy'),
                                          ('ReplacementCredential456!', 'different', 'password_confirmation_mismatch')]:
        result = client.post('/auth/me/password', json={'password': password, 'confirm_password': confirmation, 'reauthentication_token': grant})
        assert result.status_code == 400 and result.json()['detail']['error_code'] == code
    replacement = 'ReplacementCredential456!'
    result = client.post('/auth/me/password', json={'password': replacement, 'confirm_password': replacement, 'reauthentication_token': grant})
    assert result.status_code == 200, result.text
    with factory() as session:
        user = session.get(User, uid)
        assert user.failed_login_count == 0 and user.locked_until is None and user.is_active
        assert session.scalar(select(Passkey)).user_id == uid
        assert len(session.scalars(select(RefreshToken).where(RefreshToken.revoked_at.is_(None))).all()) == 1
        event = session.scalar(select(Event).where(Event.event_type == 'password_changed'))
        assert event.actor_user_id == uid and event.params is None
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD}).status_code == 401
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': replacement}).status_code == 200
    assert client.post('/auth/me/password', json={'password': replacement, 'confirm_password': replacement, 'reauthentication_token': grant}).status_code == 403


@pytest.mark.parametrize('fault', ['expired', 'session', 'password_reset', 'other_user'])
def test_reauthentication_bound_to_account_session_state_and_expiry(enrolled_client, fault):
    client, uid, factory = enrolled_client
    grant = proof(client)
    if fault == 'session':
        client.headers['authorization'] = token_for(uid, factory)
    elif fault == 'other_user':
        other = client.post('/admin/users', json={'email': 'another@example.com', 'password': PASSWORD}).json()
        client.headers['authorization'] = token_for(uuid.UUID(other['user_id']), factory)
    else:
        with factory() as session:
            if fault == 'expired':
                session.scalar(select(ReauthenticationGrant)).expires_at = int(time.time()) - 1
            else:
                session.get(User, uid).password_hash = hash_password('ResetCredential456!')
            session.commit()
    response = client.post('/auth/me/email', json={'email': 'replacement@example.com', 'reauthentication_token': grant})
    assert response.status_code == 403 and response.json()['detail']['error_code'] == 'reauthentication_required'


def test_multiple_passkeys_metadata_removal_and_owner_isolation(enrolled_client):
    client, uid, factory = enrolled_client
    first, second = Authenticator(), Authenticator()
    enroll(client, first)
    opts = options(client, 'register')
    payload = second.response(opts, register=True)
    payload['name'] = '  Windows laptop  '
    assert client.post('/auth/passkeys/register/verify', json=payload).status_code == 200
    keys = client.get('/auth/passkeys').json()['passkeys']
    assert len(keys) == 2 and client.get('/auth/me').json()['passkey_count'] == 2
    assert {k['name'] for k in keys} == {None, 'Windows laptop'}
    assert all(set(k) == {'id', 'name', 'created_at', 'last_used_at'} for k in keys)
    assert all(k['created_at'] and k['last_used_at'] is None for k in keys)
    other = client.post('/admin/users', json={'email': 'other@example.com', 'password': PASSWORD}).json()
    original_auth = client.headers['authorization']
    client.headers['authorization'] = token_for(uuid.UUID(other['user_id']), factory)
    assert client.get('/auth/passkeys').json() == {'passkeys': []}
    denied = client.delete('/auth/passkeys/' + keys[0]['id'], headers={'X-Reauthentication-Token': proof(client)})
    assert denied.status_code == 403 and denied.json()['detail']['error_code'] == 'passkey_not_owned'
    client.headers['authorization'] = original_auth
    assert client.delete('/auth/passkeys/missing', headers={'X-Reauthentication-Token': proof(client)}).status_code == 404
    for i, key in enumerate(keys):
        result = client.delete('/auth/passkeys/' + key['id'], headers={'X-Reauthentication-Token': proof(client)})
        assert result.status_code == 200, result.text
        assert len(client.get('/auth/passkeys').json()['passkeys']) == 1 - i
    # All supported accounts require a password; removing the last key is safe.
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD}).status_code == 200
    with factory() as session:
        events = session.scalars(select(Event).where(Event.event_type.in_(['passkey_registered', 'passkey_removed']))).all()
        assert len(events) == 4 and all(e.actor_user_id == uid for e in events)


def test_passkey_proof_can_change_password_without_current_password(enrolled_client):
    client, uid, _ = enrolled_client
    authenticator = Authenticator()
    enroll(client, authenticator)
    opts = options(client, 'reauthenticate')
    payload = authenticator.response(opts, register=False, user_id=uid, count=2)
    result = client.post('/auth/passkeys/reauthenticate/verify', json=payload)
    assert result.status_code == 200, result.text
    grant = result.json()['reauthentication_token']
    assert client.post('/auth/passkeys/reauthenticate/verify', json=payload).status_code == 400
    new_password = 'ReplacementCredential456!'
    changed = client.post('/auth/me/password', json={'password': new_password, 'confirm_password': new_password, 'reauthentication_token': grant})
    assert changed.status_code == 200, changed.text
    assert client.get('/auth/passkeys').json()['passkeys'][0]['last_used_at'] is not None


def test_admin_names_share_validation_and_audit_snapshot_survives_rename(enrolled_client):
    client, uid, factory = enrolled_client
    response = client.put('/admin/users/' + str(uid), json={'first_name': ' Jennifer ', 'last_name': 'DeWinter'})
    assert response.status_code == 200 and response.json()['display_name'] == 'Jennifer DeWinter'
    preferences = client.put('/admin/system-preferences', json={'default_language_code': 'es'})
    assert preferences.status_code == 200, preferences.text
    assert preferences.json()['last_updated_by_display_name'] == 'Jennifer DeWinter'
    assert preferences.json()['last_updated_by_user_id'] == str(uid)
    assert client.patch('/auth/me', json={'first_name': 'Renamed'}).status_code == 200
    assert client.get('/admin/system-preferences').json()['last_updated_by_display_name'] == 'Jennifer DeWinter'
    with factory() as session:
        add_event(session, event_type='historic_test', source='test', actor_email='deleted@example.com')
        session.commit()
    events = client.get('/admin/events').json()
    historic = next(e for e in events if e['event_type'] == 'historic_test')
    assert historic['actor_display_name'] == 'deleted@example.com'
    created = client.post('/admin/users', json={'email': ' NEW@example.com ', 'password': PASSWORD, 'first_name': ' 李 ', 'last_name': ' '})
    assert created.status_code == 201 and created.json()['display_name'] == '李' and created.json()['last_name'] is None
    assert client.put('/admin/users/' + created.json()['user_id'], json={'last_name': 'x' * 101}).status_code == 422


def test_reauthentication_lockout_and_unauthenticated_access(enrolled_client):
    client, _, _ = enrolled_client
    for _ in range(get_auth_settings().max_failed_login_count):
        assert client.post('/auth/reauthenticate', json={'current_password': 'wrong'}).status_code == 403
    assert client.post('/auth/reauthenticate', json={'current_password': PASSWORD}).json()['detail']['error_code'] == 'account_locked'
    client.headers.pop('authorization')
    assert client.get('/auth/passkeys').status_code == 401
    assert client.patch('/auth/me', json={'first_name': 'unauthorized'}).status_code == 401
    assert client.post('/auth/me/email', json={'email': 'new@example.com'}).status_code == 401


@pytest.mark.parametrize('fault', ['signature', 'handle', 'verification', 'counter', 'origin', 'expired', 'login_challenge', 'other_owner'])
def test_passkey_reauthentication_rejects_invalid_or_misbound_proof(enrolled_client, fault):
    from models import PasskeyChallenge
    from webauthn.helpers import bytes_to_base64url

    client, uid, factory = enrolled_client
    authenticator = Authenticator()
    enroll(client, authenticator)
    opts = options(client, 'login' if fault == 'login_challenge' else 'reauthenticate')
    if fault == 'expired':
        with factory() as session:
            session.scalar(select(PasskeyChallenge)).expires_at = int(time.time()) - 1
            session.commit()
    if fault == 'other_owner':
        other = client.post('/admin/users', json={'email': 'another@example.com', 'password': PASSWORD}).json()
        with factory() as session:
            session.scalar(select(Passkey)).user_id = uuid.UUID(other['user_id'])
            session.commit()
    payload = authenticator.response(opts, register=False, user_id=uuid.uuid4() if fault == 'handle' else uid,
                                     count=1 if fault == 'counter' else 2, verified=fault != 'verification',
                                     origin='https://evil.example' if fault == 'origin' else 'http://localhost')
    if fault == 'signature':
        payload['credential']['response']['signature'] = bytes_to_base64url(b'forged')
    response = client.post('/auth/passkeys/reauthenticate/verify', json=payload)
    assert response.status_code == 400 and response.json()['detail'] == {'error_code': 'passkey_failed'}
    with factory() as session:
        assert session.scalar(select(ReauthenticationGrant)) is None


def test_post_setup_enrollment_requires_recent_proof_even_without_a_passkey(enrolled_client):
    client, _, _ = enrolled_client
    assert client.post('/setup/complete', json={'default_language_code': 'en'}).status_code == 200
    assert client.post('/auth/passkeys/register/options').status_code == 403
    grant = proof(client)
    response = client.post('/auth/passkeys/register/options', json={'reauthentication_token': grant})
    assert response.status_code == 200, response.text
    assert client.post('/auth/passkeys/register/options', json={'reauthentication_token': grant}).status_code == 403


def test_sensitive_change_invalidates_existing_reset_link(enrolled_client):
    client, uid, _ = enrolled_client
    link = client.post(f'/admin/users/{uid}/password-reset-link')
    assert link.status_code == 200, link.text
    reset_token = link.json()['reset_url'].split('#token=')[1]
    result = client.post('/auth/me/email', json={'email': 'replacement@example.com', 'reauthentication_token': proof(client)})
    assert result.status_code == 200, result.text
    assert client.post('/auth/password-reset/complete', json={'token': reset_token, 'password': 'StaleRecoveryPassword123!'}).status_code == 400


def test_login_refresh_logout_rotation_and_cookie_cleanup(enrolled_client):
    client, _, _ = enrolled_client
    login = client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD})
    old = login.cookies['refresh_token']
    client.cookies.set('refresh_token', old, path='/auth')
    refreshed = client.post('/auth/refresh')
    assert refreshed.status_code == 200
    assert client.post('/auth/refresh').status_code == 401  # Old test-path cookie.
    client.cookies.set('refresh_token', refreshed.cookies['refresh_token'], path='/auth')
    logged_out = client.post('/auth/logout')
    assert logged_out.status_code == 204 and 'Max-Age=0' in logged_out.headers['set-cookie']
    assert client.post('/auth/refresh').status_code == 401


def test_existing_login_lockout_and_disabled_account(enrolled_client):
    client, uid, factory = enrolled_client
    for _ in range(get_auth_settings().max_failed_login_count):
        assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': 'wrong'}).status_code == 401
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD}).status_code == 401
    with factory() as session:
        user = session.get(User, uid)
        user.locked_until = None
        user.is_active = False
        session.commit()
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD}).status_code == 401
    assert client.get('/auth/me').status_code == 401
