import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from models import PasswordResetToken, User
from postgresql_test_support import POSTGRES_TEST_URL_ENV, temporary_postgres_database, upgrade, downgrade
from services.auth import hash_password
from services.password_reset import create_reset_link, consume_reset, PasswordResetError


def test_password_reset_migration_and_concurrent_single_use(monkeypatch):
    if not os.environ.get(POSTGRES_TEST_URL_ENV):
        pytest.skip(f'Set {POSTGRES_TEST_URL_ENV} to run PostgreSQL migration tests')
    monkeypatch.setenv('COMPASSAQ_APPLICATION_URL', 'https://compass.example.org')
    with temporary_postgres_database('password_reset') as (url, engine):
        upgrade(url, '20260905_0021')
        # Test this migration's own downgrade before later revisions. The Demo
        # provider migration (0023) intentionally cannot be downgraded.
        upgrade(url, '20260905_0022')
        assert 'password_reset_token' in inspect(engine).get_table_names()
        downgrade(url, '20260905_0021')
        assert 'password_reset_token' not in inspect(engine).get_table_names()
        upgrade(url, 'head')
        assert 'password_reset_token' in inspect(engine).get_table_names()
        uid = uuid.uuid4()
        with Session(engine) as session:
            user = User(user_id=uid, org_id=uuid.uuid4(), email='recover@example.org', password_hash=hash_password('OriginalCredential123!'), is_active=True)
            session.add(user)
            session.commit()
            link, _, _ = create_reset_link(session, uid, user)
            session.commit()
        raw = link.split('#token=')[1]
        def consume():
            with Session(engine) as session:
                try:
                    consume_reset(session, raw, 'ReplacementCredential456!')
                    return 'success'
                except PasswordResetError:
                    session.rollback()
                    return 'used'
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: consume(), range(2))) == ['success', 'used']
        with Session(engine) as session:
            saved = session.scalar(select(PasswordResetToken))
            assert saved.consumed_at is not None and saved.token_hash != raw
            session.delete(session.get(User, uid))
            session.commit()
            assert session.scalar(select(PasswordResetToken)) is None
