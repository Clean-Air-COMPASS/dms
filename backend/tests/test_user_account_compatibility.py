"""Compatibility of account changes with administrator controls and recovery."""
import uuid

from sqlalchemy import select

from models import Event, Passkey, User
from test_setup_state import isolated_setup_database  # noqa: F401
from test_passkeys import Authenticator, PASSWORD, enrolled_client, enroll, options  # noqa: F401
from test_user_account import proof


def test_admin_email_update_normalizes_and_preserves_existing_management(enrolled_client):
    client, _, _ = enrolled_client
    created = client.post('/admin/users', json={
        'email': ' ORIGINAL@example.com ', 'password': PASSWORD,
        'first_name': '  Jennifer ', 'roles': ['admin'], 'is_active': False,
    })
    assert created.status_code == 201, created.text
    uid = created.json()['user_id']
    assert created.json()['email'] == 'original@example.com'
    assert client.post('/auth/login', json={'email': 'original@example.com', 'password': PASSWORD}).status_code == 401
    updated = client.put('/admin/users/' + uid, json={'email': ' Renamed@EXAMPLE.COM ', 'is_active': True})
    assert updated.status_code == 200, updated.text
    assert updated.json()['user_id'] == uid and updated.json()['first_name'] == 'Jennifer'
    assert updated.json()['roles'] == ['admin'] and updated.json()['email'] == 'renamed@example.com'
    assert client.post('/auth/login', json={'email': 'original@example.com', 'password': PASSWORD}).status_code == 401
    assert client.post('/auth/login', json={'email': ' renamed@EXAMPLE.COM ', 'password': PASSWORD}).status_code == 200
    duplicate = client.put('/admin/users/' + uid, json={'email': ' PASSKEY@example.com '})
    assert duplicate.status_code == 409
    assert client.put('/admin/users/' + uid, json={'email': 'invalid'}).status_code == 422
    assert client.put('/admin/users/' + uid, json={'password': 'short'}).status_code == 400
    assert any(user['user_id'] == uid for user in client.get('/admin/users').json())
    assert client.get('/admin/users/' + uid).json()['display_name'] == 'Jennifer'


def test_missing_password_proof_and_removal_of_last_method_fail_closed(enrolled_client):
    client, uid, factory = enrolled_client
    password = 'ReplacementCredential456!'
    assert client.post('/auth/me/password', json={'password': password, 'confirm_password': password}).status_code == 403
    authenticator = Authenticator()
    enroll(client, authenticator)
    key_id = client.get('/auth/passkeys').json()['passkeys'][0]['id']
    assert client.delete('/auth/passkeys/' + key_id).status_code == 403
    # No supported creation path writes this password-less state. Exercise the
    # defensive policy for a future account type or damaged password record.
    with factory() as session:
        session.get(User, uid).password_hash = '!disabled-password'
        session.commit()
    opts = options(client, 'reauthenticate')
    response = client.post('/auth/passkeys/reauthenticate/verify', json=authenticator.response(opts, register=False, user_id=uid, count=2))
    assert response.status_code == 200, response.text
    result = client.delete('/auth/passkeys/' + key_id, headers={'X-Reauthentication-Token': response.json()['reauthentication_token']})
    assert result.status_code == 409 and result.json()['detail']['error_code'] == 'last_authentication_method'
    with factory() as session:
        assert session.get(Passkey, key_id) is not None


def test_actual_recovery_invalidates_proof_and_uses_new_email(enrolled_client):
    client, uid, _ = enrolled_client
    result = client.post('/auth/me/email', json={'email': 'new@example.com', 'reauthentication_token': proof(client)})
    assert result.status_code == 200
    grant = proof(client)
    link = client.post(f'/admin/users/{uid}/password-reset-link')
    assert link.status_code == 200, link.text
    token = link.json()['reset_url'].split('#token=')[1]
    reset = client.post('/auth/password-reset/complete', json={'token': token, 'password': 'RecoveryCredential456!'})
    assert reset.status_code == 200
    stale = client.post('/auth/me/email', json={'email': 'stale@example.com', 'reauthentication_token': grant})
    assert stale.status_code == 403
    assert client.post('/auth/login', json={'email': 'new@example.com', 'password': 'RecoveryCredential456!'}).status_code == 200


def test_historic_actor_without_name_or_resolvable_user_keeps_email(enrolled_client):
    client, _, factory = enrolled_client
    with factory() as session:
        session.add(Event(event_type='legacy_actor', source='test', actor_user_id=uuid.uuid4(),
                          actor_email='historic@example.com', actor_display_name=None))
        session.commit()
    event = next(e for e in client.get('/admin/events').json() if e['event_type'] == 'legacy_actor')
    assert event['actor_display_name'] == event['actor_email'] == 'historic@example.com'
