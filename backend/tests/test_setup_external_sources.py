from __future__ import annotations

import uuid

import pytest
import requests
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

import models
from api.routes import setup
from services.external_sources import (
    RunnableReason,
    derive_external_source_state,
    ensure_builtin_external_apis,
)


def test_setup_initializes_source_enabled_from_supplied_credentials_without_provider_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("setup must not contact a provider")
        ),
    )
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'setup.sqlite'}")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        ensure_builtin_external_apis(session)
        session.add(models.SystemSettings(is_system_setup_complete=False))
        session.commit()

        available = setup.list_data_sources(session)
        assert {source.name for source in available.data_sources} == {
            "Demo Data",
            "OpenAQ",
            "PurpleAir",
            "AirGradient",
        }
        assert {source.provider_code for source in available.data_sources} == {
            "demo",
            "openaq",
            "purpleair",
            "airgradient",
        }
        assert all(source.enabled is False for source in available.data_sources)
        assert all(source.is_runnable is False for source in available.data_sources)

        openaq = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "openaq"
            )
        )
        response = setup.configure_data_source(
            setup.ConfigureDataSourceRequest(
                external_api_id=openaq.external_api_id,
                api_key="setup-key",
                enabled=True,
            ),
            session,
        )
        assert response.success is True
        session.refresh(openaq)
        assert openaq.enabled is True
        assert openaq.api_key == "setup-key"

        setup.configure_data_source(
            setup.ConfigureDataSourceRequest(
                external_api_id=openaq.external_api_id,
                api_key=None,
                enabled=False,
            ),
            session,
        )
        session.refresh(openaq)
        assert openaq.enabled is False
        assert openaq.api_key is None

        openaq.api_key = "stored-key"
        session.commit()
        setup.configure_data_source(
            setup.ConfigureDataSourceRequest(
                external_api_id=openaq.external_api_id,
                enabled=False,
            ),
            session,
        )
        session.refresh(openaq)
        assert openaq.enabled is False
        assert openaq.api_key == "stored-key"

        purpleair = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "purpleair"
            )
        )
        setup.configure_data_source(
            setup.ConfigureDataSourceRequest(
                external_api_id=purpleair.external_api_id,
                api_key="purple-key",
                enabled=True,
            ),
            session,
        )
        session.refresh(purpleair)
        purpleair_state = derive_external_source_state(
            purpleair,
            {"COMPASSAQ_ENV": "development", "ENABLE_PAID_API_IMPORTS": "false"},
        )
        assert purpleair.enabled is True
        assert purpleair_state.is_configured is True
        assert purpleair_state.is_runnable is True
        assert purpleair_state.runnable_reason == RunnableReason.READY

        airgradient = session.scalar(
            select(models.ExternalAPI).where(
                models.ExternalAPI.provider_code == "airgradient"
            )
        )
        setup.configure_data_source(
            setup.ConfigureDataSourceRequest(
                external_api_id=airgradient.external_api_id,
                api_key="airgradient-setup-key",
                enabled=True,
            ),
            session,
        )
        session.refresh(airgradient)
        assert airgradient.api_key == "airgradient-setup-key"
        assert airgradient.enabled is True

        assert not hasattr(setup, "verify_data_source_api_key")
        assert not hasattr(setup, "verify_geoapify_api_key")


def test_setup_admin_can_only_be_created_once(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'admin.sqlite'}")

    @event.listens_for(engine, "connect")
    def _register_postgres_uuid_default_for_sqlite(dbapi_connection, _connection_record):
        dbapi_connection.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        session.add(models.SystemSettings(is_system_setup_complete=False))
        session.commit()

        first = setup.create_initial_admin(
            setup.CreateAdminRequest(
                email="first@example.com",
                password="CorrectHorseBatteryStaple!",
                confirm_password="CorrectHorseBatteryStaple!",
            ),
            session,
        )
        assert first.success is True

        with pytest.raises(HTTPException) as exc_info:
            setup.create_initial_admin(
                setup.CreateAdminRequest(
                    email="second@example.com",
                    password="AnotherLongPassword!123",
                    confirm_password="AnotherLongPassword!123",
                ),
                session,
            )

        assert exc_info.value.status_code == 409
        assert session.scalar(select(models.User).where(models.User.email == "second@example.com")) is None
