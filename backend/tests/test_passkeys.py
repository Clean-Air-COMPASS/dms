"""Real WebAuthn signatures, without a physical authenticator or external services."""
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url as encode

from api.main import app
from models import Passkey, PasskeyChallenge, User
from test_setup_state import isolated_setup_database  # noqa: F401

ORIGIN = "http://localhost"
PASSWORD = "SetupStrongCredential123!"


class Authenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = uuid.uuid4().bytes

    def response(self, options, *, register, origin=ORIGIN, verified=True, count=1, user_id=None):
        client_data = json.dumps({"type": "webauthn.create" if register else "webauthn.get",
                                  "challenge": options["challenge"], "origin": origin}).encode()
        flags = 1 | (4 if verified else 0) | (64 if register else 0)
        auth_data = hashlib.sha256(b"localhost").digest() + bytes([flags]) + count.to_bytes(4, "big")
        response = {"clientDataJSON": encode(client_data)}
        if register:
            public = self.key.public_key().public_numbers()
            cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: public.x.to_bytes(32, "big"), -3: public.y.to_bytes(32, "big")})
            auth_data += bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + cose
            response["attestationObject"] = encode(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data}))
        else:
            signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
            response.update(authenticatorData=encode(auth_data), signature=encode(signature), userHandle=encode(user_id.bytes))
        return {"credential": {"id": encode(self.credential_id), "rawId": encode(self.credential_id),
                                "type": "public-key", "response": response}}


@pytest.fixture()
def enrolled_client(isolated_setup_database):
    _, _, factory = isolated_setup_database
    client = TestClient(app, base_url=ORIGIN, headers={"origin": ORIGIN})
    admin = client.post('/setup/admin', json={"email": "passkey@example.com", "password": PASSWORD, "confirm_password": PASSWORD})
    assert admin.status_code == 200, admin.text
    user_id = uuid.UUID(admin.json()["user_id"])
    login = client.post('/auth/login', json={"email": "passkey@example.com", "password": PASSWORD})
    assert login.status_code == 200, login.text
    client.headers['authorization'] = f"Bearer {login.json()['access_token']}"
    return client, user_id, factory


def options(client, purpose):
    body = None
    if purpose == 'register':
        # Additional enrollment now requires recent proof. Keep the first-run
        # ceremony exercised without it, matching the existing setup client.
        keys = client.get('/auth/passkeys').json()['passkeys']
        if keys or not client.get('/setup/status').json()['is_setup_required']:
            proof = client.post('/auth/reauthenticate', json={'current_password': PASSWORD})
            assert proof.status_code == 200, proof.text
            body = {'reauthentication_token': proof.json()['reauthentication_token']}
    response = client.post(f'/auth/passkeys/{purpose}/options', json=body)
    assert response.status_code == 200, response.text
    # Production routes use /api at the reverse proxy; TestClient calls the ASGI paths.
    client.cookies.set('passkey_ceremony', response.cookies['passkey_ceremony'], path='/auth/passkeys')
    return response.json()


def enroll(client, authenticator):
    opts = options(client, 'register')
    assert opts['authenticatorSelection']['residentKey'] == 'required'
    assert opts['authenticatorSelection']['userVerification'] == 'required'
    result = client.post('/auth/passkeys/register/verify', json=authenticator.response(opts, register=True))
    assert result.status_code == 200, result.text


def test_register_finish_setup_and_sign_in_without_password(enrolled_client):
    client, user_id, factory = enrolled_client
    authenticator = Authenticator()
    enroll(client, authenticator)
    assert client.post('/setup/complete', json={'default_language_code': 'en'}).status_code == 200
    client.headers.pop('authorization')
    client.cookies.clear()
    opts = options(client, 'login')
    payload = authenticator.response(opts, register=False, user_id=user_id, count=2)
    result = client.post('/auth/passkeys/login/verify', json=payload)
    assert result.status_code == 200, result.text
    assert result.json()['access_token']
    assert 'HttpOnly' in result.headers['set-cookie']
    assert client.get('/auth/me', headers={'authorization': f"Bearer {result.json()['access_token']}"}).json()['user_id'] == str(user_id)
    assert client.post('/auth/passkeys/login/verify', json=payload).status_code == 400
    with factory() as session:
        saved = session.scalar(select(Passkey))
        assert saved.sign_count == 2
        assert saved.user_id == user_id
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': PASSWORD}).status_code == 200
    assert client.post('/auth/login', json={'email': 'passkey@example.com', 'password': 'wrong'}).status_code == 401


@pytest.mark.parametrize('fault', ['origin', 'verification', 'challenge', 'expired', 'missing_cookie', 'malformed'])
def test_registration_rejects_invalid_proof_without_leaking_details(enrolled_client, fault):
    client, _, factory = enrolled_client
    authenticator = Authenticator()
    opts = options(client, 'register')
    if fault == 'challenge':
        opts['challenge'] = encode(b'wrong-challenge')
    if fault == 'expired':
        with factory() as session:
            session.scalar(select(PasskeyChallenge)).expires_at = int(time.time()) - 1
            session.commit()
    if fault == 'missing_cookie':
        client.cookies.clear()
    payload = authenticator.response(opts, register=True, origin='https://evil.example' if fault == 'origin' else ORIGIN,
                                     verified=fault != 'verification')
    if fault == 'malformed':
        payload['credential'] = {'id': 'SECRET SECURITY DETAILS'}
    result = client.post('/auth/passkeys/register/verify', json=payload)
    assert result.status_code == 400, result.text
    assert result.json() == {'detail': {'error_code': 'passkey_failed'}}
    with factory() as session:
        assert session.scalar(select(Passkey)) is None


def test_enrollment_requires_authenticated_owner_and_same_origin(enrolled_client):
    client, _, _ = enrolled_client
    assert client.post('/auth/passkeys/register/options', headers={'origin': 'https://evil.example'}).status_code == 400
    client.headers.pop('authorization')
    assert client.post('/auth/passkeys/register/options').status_code == 401


@pytest.mark.parametrize('fault', ['signature', 'handle', 'verification', 'counter', 'disabled', 'locked', 'origin'])
def test_passkey_sign_in_rejects_invalid_or_ineligible_credentials(enrolled_client, fault):
    client, user_id, factory = enrolled_client
    authenticator = Authenticator()
    enroll(client, authenticator)
    opts = options(client, 'login')
    payload = authenticator.response(opts, register=False, user_id=uuid.uuid4() if fault == 'handle' else user_id,
                                     count=1 if fault == 'counter' else 2, verified=fault != 'verification',
                                     origin='https://evil.example' if fault == 'origin' else ORIGIN)
    if fault == 'signature':
        payload['credential']['response']['signature'] = encode(b'forged signature')
    if fault in {'disabled', 'locked'}:
        with factory() as session:
            user = session.get(User, user_id)
            if fault == 'disabled':
                user.is_active = False
            else:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
            session.commit()
    result = client.post('/auth/passkeys/login/verify', json=payload)
    assert result.status_code == 400, result.text
    assert result.json() == {'detail': {'error_code': 'passkey_failed'}}


def test_interrupted_setup_stays_resumable_without_passkey(enrolled_client):
    client, _, _ = enrolled_client
    assert client.get('/setup/status').json()['has_users'] is True
    assert client.post('/setup/complete', json={'default_language_code': 'es'}).status_code == 200


@pytest.mark.parametrize('payload', [{'credential': 'SECRET'}, ['SECRET'], {'credential': {'response': 'SECRET'}}])
def test_malformed_requests_never_echo_credential_input(enrolled_client, payload):
    client, _, _ = enrolled_client
    options(client, 'register')
    response = client.post('/auth/passkeys/register/verify', json=payload)
    assert response.status_code == 400
    assert response.json() == {'detail': {'error_code': 'passkey_failed'}}


def test_configured_origin_is_exact_and_not_taken_from_untrusted_header(enrolled_client, monkeypatch):
    client, _, _ = enrolled_client
    monkeypatch.setenv('PASSKEY_ORIGIN', 'https://air.example.org:8443')
    assert client.post('/auth/passkeys/register/options').status_code == 400
    response = client.post('/auth/passkeys/register/options', headers={'origin': 'https://air.example.org:8443'})
    assert response.status_code == 200
    assert response.json()['rp']['id'] == 'air.example.org'
    assert 'Secure' in response.headers['set-cookie']
    assert client.post('/auth/passkeys/register/options', headers={'origin': 'https://air.example.org'}).status_code == 400


def test_duplicate_registration_is_rejected_and_excluded(enrolled_client):
    client, _, factory = enrolled_client
    authenticator = Authenticator()
    enroll(client, authenticator)
    opts = options(client, 'register')
    assert opts['excludeCredentials'][0]['id'] == encode(authenticator.credential_id)
    response = client.post('/auth/passkeys/register/verify', json=authenticator.response(opts, register=True))
    assert response.status_code == 400
    with factory() as session:
        assert len(session.scalars(select(Passkey)).all()) == 1


def test_passkey_options_share_login_rate_limit(enrolled_client, monkeypatch):
    from api.routes import passkeys
    from fastapi import HTTPException

    client, _, _ = enrolled_client
    calls = []

    def exhausted(*args, **kwargs):
        calls.append(kwargs['ip_address'])
        raise HTTPException(429, 'Too many login attempts')

    monkeypatch.setattr(passkeys, '_enforce_login_rate_limit', exhausted)
    assert client.post('/auth/passkeys/login/options').status_code == 429
    assert len(calls) == 1


def test_passkey_migration_upgrade_and_downgrade(isolated_setup_database):
    import importlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    _, engine, _ = isolated_setup_database
    migration = importlib.import_module('migrations.versions.20260905_0021_passkeys')
    with engine.begin() as connection:
        PasskeyChallenge.__table__.drop(connection)
        Passkey.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {'passkey', 'passkey_challenge'} <= set(inspect(connection).get_table_names())
            migration.downgrade()
            assert 'passkey' not in inspect(connection).get_table_names()
            assert 'user' in inspect(connection).get_table_names()
