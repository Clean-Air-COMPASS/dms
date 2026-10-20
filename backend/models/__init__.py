import uuid
import re
import sqlite3
from datetime import datetime, time
from typing import Any, Optional
from enum import Enum

from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column, relationship, synonym
from sqlalchemy import BigInteger, Integer, String, Text, ForeignKey, DateTime, Time, func, Float, Boolean, JSON, UniqueConstraint, Index, CheckConstraint, event, text
from sqlalchemy.engine import Engine
from sqlalchemy import select as select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geometry


class Base(DeclarativeBase):
    pass


# PostgreSQL needs 64-bit identifiers for ingestion-scale tables. SQLite must
# retain the exact INTEGER spelling so its rowid-backed autoincrement works in
# the existing local and test databases.
INGESTION_ID_TYPE = BigInteger().with_variant(Integer, "sqlite")

# PostgreSQL stores the canonical point. SQLite remains available for the
# existing non-spatial unit tests, where the point is stored as readable WKT.
DEVICE_LOCATION_TYPE = Text().with_variant(
    Geometry(
        geometry_type="POINT",
        srid=4326,
        dimension=2,
        spatial_index=False,
    ),
    "postgresql",
)


_SQLITE_POINT_PATTERN = re.compile(
    r"^POINT\s*\(\s*([^\s]+)\s+([^\s]+)\s*\)$", re.IGNORECASE
)


def _sqlite_point_coordinate(value: str | None, coordinate_index: int) -> float | None:
    """Read X or Y from the WKT used by non-spatial SQLite tests."""
    if value is None:
        return None
    match = _SQLITE_POINT_PATTERN.match(str(value).strip())
    if match is None:
        return None
    return float(match.group(coordinate_index))


@event.listens_for(Engine, "connect")
def _register_sqlite_spatial_read_functions(dbapi_connection, _connection_record) -> None:
    """Provide coordinate reads for the repository's SQLite unit-test fallback."""
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.create_function(
        "ST_X", 1, lambda value: _sqlite_point_coordinate(value, 1)
    )
    dbapi_connection.create_function(
        "ST_Y", 1, lambda value: _sqlite_point_coordinate(value, 2)
    )


                            
class User(Base):
    __tablename__ = "user"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_failed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    preferred_language_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    roles: Mapped[list["Role"]] = relationship(
        secondary="user_role",
        back_populates="users",
    )

    @property
    def display_name(self) -> str:
        from services.user_identity import display_name
        return display_name(self.first_name, self.last_name, self.email)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email"),
        Index("ix_user_org_id", "org_id"),
        CheckConstraint(
            "preferred_language_code IS NULL OR preferred_language_code IN ('en', 'es')",
            name="ck_user_preferred_language_code",
        ),
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), index=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="SET NULL"))


class Passkey(Base):
    __tablename__ = "passkey"

    credential_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), index=True)
    public_key: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(BigInteger)
    rp_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Historical enrollment/use times are unknown, not migration time.
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)


class ReauthenticationGrant(Base):
    __tablename__ = "reauthentication_grant"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), index=True)
    access_token_jti: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    authentication_state: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)


class PasskeyChallenge(Base):
    __tablename__ = "passkey_challenge"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    challenge: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(16))
    origin: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)


class Role(Base):
    __tablename__ = "role"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship(
        secondary="user_role",
        back_populates="roles",
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_role_name"),
    )


class UserRole(Base):
    __tablename__ = "user_role"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role.role_id", ondelete="CASCADE"),
        primary_key=True,
    )


class RefreshToken(Base):
    __tablename__ = "refresh_token"

    refresh_token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_refresh_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_token.refresh_token_id", ondelete="SET NULL"),
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("ix_refresh_token_user_id", "user_id"),
        Index("ix_refresh_token_expires_at", "expires_at"),
        Index("ix_refresh_token_token_hash", "token_hash"),
    )


class AuthLoginAttempt(Base):
    __tablename__ = "auth_login_attempt"

    auth_login_attempt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Unit(Base):
    __tablename__ = "unit"
    unit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
                                                      
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
                                           
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
                                                             
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Parameter(Base):
    __tablename__ = "parameter"
    parameter_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
                                                
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
                                               
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
                                               
    default_unit_id: Mapped[int] = mapped_column(ForeignKey("unit.unit_id", ondelete="RESTRICT"), nullable=False)
                                                                                               
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

                                                                       
    aggregation_rules: Mapped[list["ParameterAggregationRule"]] = relationship(
        back_populates="parameter",
        cascade="all, delete-orphan",
        order_by="ParameterAggregationRule.parameter_aggregation_rule_id",
    )
    supported_units: Mapped[list["ParameterSupportedUnit"]] = relationship(
        back_populates="parameter",
        cascade="all, delete-orphan",
        order_by="ParameterSupportedUnit.unit_id",
    )


class ParameterSupportedUnit(Base):
    """A unit that administrators may use for one parameter's QC rules."""

    __tablename__ = "parameter_supported_unit"
    parameter_id: Mapped[int] = mapped_column(
        ForeignKey("parameter.parameter_id", ondelete="CASCADE"),
        primary_key=True,
    )
    unit_id: Mapped[int] = mapped_column(
        ForeignKey("unit.unit_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    parameter: Mapped[Parameter] = relationship(back_populates="supported_units")
    unit: Mapped[Unit] = relationship()


class UpdatePolicy(Enum):
    """Tri-state update policy for measurement upserts.

    - ALLOW: always update existing duplicates
    - DENY: never update existing duplicates
    - INHERIT: defer to parent (sensor defers to device); default behavior
    """
    ALLOW = "allow"
    DENY = "deny"
    INHERIT = "inherit"


class Device(Base):
    __tablename__ = "device"
    device_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
                                                                                            
    name: Mapped[str] = mapped_column(String(120), nullable=False)
                                                                           
    friendly_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
                                                                            
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Stable machine-readable path used to distinguish provider transports that
    # can expose the same provider location ID (for example authenticated and
    # public-reference AirGradient access).
    acquisition_path: Mapped[str] = mapped_column(
        String(64), nullable=False, default="unspecified", server_default="unspecified"
    )

    # Device-level data attribution is intentionally explicit and small. The
    # ExternalAPI relationship identifies the transport/data platform; these
    # fields preserve origin, contributor, place, and license facts supplied by
    # the provider without embedding legal text in measurements.
    hardware_provider_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    contributor_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    contributor_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    license_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    license_share_alike: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
                                                                       
    external_api_id: Mapped[int] = mapped_column(ForeignKey("external_api.external_api_id", ondelete="RESTRICT"), nullable=False, index=True)
                                                                                                            
    manual_data_source_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
                                                                
    location: Mapped[Any | None] = mapped_column(DEVICE_LOCATION_TYPE, nullable=True)
    # Public contracts retain these names, but only the PostGIS point is stored.
    latitude: Mapped[float | None] = column_property(func.ST_Y(location))
    longitude: Mapped[float | None] = column_property(func.ST_X(location))
                                                                                          
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
                                                                                   
                                                                             
    allow_updates: Mapped[UpdatePolicy] = mapped_column(
        SAEnum(UpdatePolicy, name="updatepolicy", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=UpdatePolicy.INHERIT.value,
    )
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sensors: Mapped[list["Sensor"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    location_history: Mapped[list["DeviceLocationHistory"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        order_by="DeviceLocationHistory.effective_from"
    )
    external_api: Mapped["ExternalAPI"] = relationship(back_populates=None)

    __table_args__ = (
        UniqueConstraint(
            "external_api_id",
            "external_id",
            "acquisition_path",
            name="uq_device_external_api_external_id_acquisition_path",
        ),
    )


class PurpleAirImportState(Base):
    """Successful poll times, shared by manual and scheduled importer processes."""

    __tablename__ = "purpleair_import_state"
    device_id: Mapped[int] = mapped_column(
        ForeignKey("device.device_id", ondelete="CASCADE"), primary_key=True
    )
    metadata_refreshed_at: Mapped[Optional["DateTime"]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    history_polled_at: Mapped[Optional["DateTime"]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Sensor(Base):
    __tablename__ = "sensor"
    sensor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.device_id", ondelete="CASCADE"), nullable=False)
                            
    parameter_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("parameter.parameter_id", ondelete="SET NULL"), nullable=True, index=True
    )
                                          
    unit_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("unit.unit_id", ondelete="SET NULL"), nullable=True, index=True
    )
                                                                                        
    aggregation_period_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("aggregation_period.aggregation_period_id", ondelete="SET NULL"), nullable=True, index=True
    )
    hourly_concentration_provenance: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    hourly_timestamp_semantics: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    expected_frequency_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    measurement_duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    source_aggregation_duration_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    measurement_timestamp_semantics: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    measurement_metadata_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    measurement_metadata_managed_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    acquisition_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acquisition_examined_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
                                                                                 
    external_sensor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
                                                     
    allow_updates: Mapped[UpdatePolicy] = mapped_column(
        SAEnum(UpdatePolicy, name="updatepolicy", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=UpdatePolicy.INHERIT.value,
    )
    created_at:  Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="sensors")

    __table_args__ = (
        UniqueConstraint(
            "device_id",
            "external_sensor_id",
            name="uq_sensor_device_external_sensor_id",
        ),
    )


class Measurement(Base):
    __tablename__ = "measurement"
    measurement_id: Mapped[int] = mapped_column(
        INGESTION_ID_TYPE, primary_key=True, autoincrement=True
    )
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensor.sensor_id", ondelete="CASCADE"), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
                         
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
                                                                 
    qc_flags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
                                                                       
    qc_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

                                                    
    sensor: Mapped[Optional[Sensor]] = relationship(back_populates=None, foreign_keys=[sensor_id])

    __table_args__ = (
        UniqueConstraint("sensor_id", "observed_at", name="uq_measurement_sensor_observed"),
        Index("ix_measurement_sensor_observed_at", "sensor_id", "observed_at"),
    )


class ExternalAPI(Base):
    __tablename__ = "external_api"
    external_api_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_code: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
                                                                           
    api_key: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
                                                                       
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DemoImportState(Base):
    """One-time seed eligibility and activation, never editable source params."""

    __tablename__ = "demo_import_state"
    external_api_id: Mapped[int] = mapped_column(
        ForeignKey("external_api.external_api_id", ondelete="RESTRICT"), primary_key=True
    )
    initial_seed_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    activated_at: Mapped[Optional["DateTime"]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DeviceLocationHistory(Base):
    __tablename__ = "device_location_history"
    device_location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.device_id", ondelete="CASCADE"), nullable=False, index=True)
    location: Mapped[Any | None] = mapped_column(DEVICE_LOCATION_TYPE, nullable=True)
    latitude: Mapped[Optional[float]] = column_property(func.ST_Y(location))
    longitude: Mapped[Optional[float]] = column_property(func.ST_X(location))
    effective_from: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[Optional["DateTime"]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="location_history")


                          

class JobStatus(Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"


class JobExecutionTrigger(Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class JobSchedule(Base):
    __tablename__ = "job_schedule"
    job_schedule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
                                              
    task: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
                                                    
    cron_expr: Mapped[str] = mapped_column(String(64), nullable=False)
                                
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
            
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", index=True)
                                                                    
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
                                                                      
    allow_overlap: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobRun(Base):
    __tablename__ = "job_run"
    job_run_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_schedule_id: Mapped[int] = mapped_column(ForeignKey("job_schedule.job_schedule_id", ondelete="CASCADE"), nullable=False, index=True)
                                                                               
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=JobStatus.RUNNING.value)
    execution_trigger: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=JobExecutionTrigger.SCHEDULED.value,
    )
    started_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    finished_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "execution_trigger IN ('scheduled', 'manual')",
            name="ck_job_run_execution_trigger",
        ),
    )


                      

class QCRule(Base):
    __tablename__ = "qc_rule"
    qc_rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    check_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sensor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("sensor.sensor_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    parameter_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("parameter.parameter_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    external_api_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("external_api.external_api_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    aggregate_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    # NULL means inherit. False and True are explicit overrides.
    enabled_override: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    failure_action_override: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_unit_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("unit.unit_id", ondelete="RESTRICT"),
        nullable=True,
    )

    # Temporary names used by the row-based administration API. The resolver
    # and new backend code use the explicit override terminology above.
    enabled = synonym("enabled_override")
    params = synonym("settings")

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    draft_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft_params = synonym("draft_settings")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "(sensor_id IS NOT NULL AND parameter_id IS NULL AND external_api_id IS NULL) OR "
            "(sensor_id IS NULL AND parameter_id IS NOT NULL AND external_api_id IS NULL) OR "
            "(sensor_id IS NULL AND parameter_id IS NOT NULL AND external_api_id IS NOT NULL)",
            name="ck_qc_rule_valid_scope",
        ),
        CheckConstraint(
            "failure_action_override IS NULL OR "
            "failure_action_override IN ('flag_for_review', 'mark_invalid')",
            name="ck_qc_rule_failure_action",
        ),
        Index(
            "uq_qc_rule_parameter_generic",
            "check_code",
            "parameter_id",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NULL"
            ),
        ),
        Index(
            "uq_qc_rule_parameter_unit_generic",
            "check_code",
            "parameter_id",
            "policy_unit_id",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_qc_rule_parameter_aggregate",
            "check_code",
            "parameter_id",
            "aggregate_code",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NULL"
            ),
        ),
        Index(
            "uq_qc_rule_parameter_unit_aggregate",
            "check_code",
            "parameter_id",
            "policy_unit_id",
            "aggregate_code",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_qc_rule_source_generic",
            "check_code",
            "external_api_id",
            "parameter_id",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NULL"
            ),
        ),
        Index(
            "uq_qc_rule_source_unit_generic",
            "check_code",
            "external_api_id",
            "parameter_id",
            "policy_unit_id",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_qc_rule_source_aggregate",
            "check_code",
            "external_api_id",
            "parameter_id",
            "aggregate_code",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NULL"
            ),
        ),
        Index(
            "uq_qc_rule_source_unit_aggregate",
            "check_code",
            "external_api_id",
            "parameter_id",
            "policy_unit_id",
            "aggregate_code",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NULL AND external_api_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_qc_rule_sensor_generic",
            "check_code",
            "sensor_id",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NULL"
            ),
        ),
        Index(
            "uq_qc_rule_sensor_unit_generic",
            "check_code",
            "sensor_id",
            "policy_unit_id",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_qc_rule_sensor_aggregate",
            "check_code",
            "sensor_id",
            "aggregate_code",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NULL"
            ),
        ),
        Index(
            "uq_qc_rule_sensor_unit_aggregate",
            "check_code",
            "sensor_id",
            "policy_unit_id",
            "aggregate_code",
            unique=True,
            postgresql_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
            sqlite_where=text(
                "sensor_id IS NOT NULL AND aggregate_code IS NOT NULL "
                "AND policy_unit_id IS NOT NULL"
            ),
        ),
    )


class MeasurementQCResult(Base):
    __tablename__ = "measurement_qc_result"
    measurement_qc_result_id: Mapped[int] = mapped_column(
        INGESTION_ID_TYPE, primary_key=True, autoincrement=True
    )
    measurement_id: Mapped[int] = mapped_column(
        INGESTION_ID_TYPE,
        ForeignKey("measurement.measurement_id", ondelete="CASCADE"),
        nullable=False,
    )
    parameter_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("parameter.parameter_id", ondelete="SET NULL"), nullable=True, index=True)
    aggregate_code: Mapped[str] = mapped_column(String(32), nullable=False)
    check_code: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="info")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    params_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evaluation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="failed"
    )
    failure_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    policy_provenance: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plugin_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, server_default="ingest")
    qc_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        UniqueConstraint("measurement_id", "check_code", name="uq_mqc_result_measurement_check"),
        Index(
            "ix_mqc_result_baseline_warmup_measurement",
            "measurement_id",
            postgresql_where=text(
                "check_code = 'baseline_drift' "
                "AND evaluation_status = 'indeterminate' "
                "AND reason_code = 'insufficient_history'"
            ),
            sqlite_where=text(
                "check_code = 'baseline_drift' "
                "AND evaluation_status = 'indeterminate' "
                "AND reason_code = 'insufficient_history'"
            ),
        ),
        CheckConstraint(
            "evaluation_status IN ('failed', 'indeterminate')",
            name="ck_mqc_result_evaluation_status",
        ),
        CheckConstraint(
            "failure_action IS NULL OR failure_action IN ('flag_for_review', 'mark_invalid')",
            name="ck_mqc_result_failure_action",
        ),
    )


                                                                
class AggregationPeriod(Base):
    __tablename__ = "aggregation_period"
    aggregation_period_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
                                                  
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_rolling: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
                                                                   
    expected_interval: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParameterAggregationRule(Base):
    __tablename__ = "parameter_aggregation_rule"
    parameter_aggregation_rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("parameter.parameter_id", ondelete="CASCADE"), nullable=False, index=True)
    aggregation_period_id: Mapped[int] = mapped_column(ForeignKey("aggregation_period.aggregation_period_id", ondelete="CASCADE"), nullable=False, index=True)

    rounding_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="round")
    rounding_precision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    truncation_method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    truncation_precision: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thresholds: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    valid_from: Mapped[Optional["DateTime"]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[Optional["DateTime"]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

                   
    parameter: Mapped["Parameter"] = relationship(back_populates="aggregation_rules")
    aggregation_period: Mapped[AggregationPeriod] = relationship(back_populates=None)

    __table_args__ = (
        UniqueConstraint("parameter_id", "aggregation_period_id", name="uq_parameter_agg_parameter_period"),
    )


class ParameterAggregationRollup(Base):
    __tablename__ = "parameter_aggregation_rollup"
    parameter_aggregation_rollup_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parameter_id: Mapped[int] = mapped_column(ForeignKey("parameter.parameter_id", ondelete="CASCADE"), nullable=False, index=True)
    from_aggregation_period_id: Mapped[int] = mapped_column(ForeignKey("aggregation_period.aggregation_period_id", ondelete="CASCADE"), nullable=False, index=True)
    to_aggregation_period_id: Mapped[int] = mapped_column(ForeignKey("aggregation_period.aggregation_period_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("parameter_id", "from_aggregation_period_id", "to_aggregation_period_id", name="uq_param_rollup_from_to"),
    )


                                                  
class Event(Base):
    __tablename__ = "event"
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default="openaq_importer")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="info")
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    actor_display_name: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    device_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("device.device_id", ondelete="SET NULL"), nullable=True, index=True)
    sensor_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sensor.sensor_id", ondelete="SET NULL"), nullable=True, index=True)
    external_sensor_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    endpoint: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


                                                                         
class SystemSettings(Base):
    """
    Stores global platform configuration in a single row.
    Contains API keys and other settings that should only be exposed through
    authenticated admin APIs when needed.
    """
    __tablename__ = "system_settings"
    system_settings_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    is_system_setup_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    geoapify_api_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    default_language_code: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
        default="en",
        server_default=text("'en'"),
    )
    system_timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        server_default="UTC",
    )
    default_reference_devices_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
                
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "default_language_code IS NULL OR default_language_code IN ('en', 'es')",
            name="ck_system_settings_default_language_code",
        ),
        CheckConstraint(
            "length(trim(system_timezone)) > 0",
            name="ck_system_settings_timezone",
        ),
    )


class EmailSettings(Base):
    """Stores platform-wide email transport and administrator-summary settings.

    The SMTP password is reversibly encrypted because the SMTP client must use
    it later. Only ciphertext belongs in this model; plaintext is accepted and
    handled by the email configuration service.
    """

    __tablename__ = "email_settings"

    email_settings_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    smtp_host: Mapped[str | None] = mapped_column(String(253), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_security_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    smtp_username: Mapped[str | None] = mapped_column(String(512), nullable=True)
    smtp_password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    from_display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reply_to_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    administrator_recipients: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )
    administrator_summary_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    administrator_summary_cadence: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="daily",
        server_default="daily",
    )
    administrator_summary_daily_send_time: Mapped["Time"] = mapped_column(
        Time(timezone=False),
        nullable=False,
        default=lambda: time(7, 0),
        server_default=text("'07:00:00'"),
    )
    administrator_summary_reporting_timezone_override: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        default=None,
        server_default=None,
    )
    administrator_summary_effective_at: Mapped[Optional["DateTime"]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_test_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_test_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_tested_at: Mapped[Optional["DateTime"]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "email_settings_id = 1",
            name="ck_email_settings_singleton",
        ),
        CheckConstraint(
            "smtp_port IS NULL OR smtp_port BETWEEN 1 AND 65535",
            name="ck_email_settings_smtp_port",
        ),
        CheckConstraint(
            "smtp_security_mode IS NULL OR "
            "smtp_security_mode IN ('starttls', 'ssl_tls', 'none')",
            name="ck_email_settings_security_mode",
        ),
        CheckConstraint(
            "administrator_summary_cadence IN "
            "('daily', 'hourly', 'every_15_minutes')",
            name="ck_email_settings_administrator_summary_cadence",
        ),
        CheckConstraint(
            "administrator_summary_reporting_timezone_override IS NULL OR "
            "length(trim(administrator_summary_reporting_timezone_override)) > 0",
            name="ck_email_settings_administrator_summary_timezone_override",
        ),
        CheckConstraint(
            "(last_test_status IS NULL "
            "AND last_test_error_code IS NULL "
            "AND last_tested_at IS NULL) "
            "OR (last_test_status = 'success' "
            "AND last_test_error_code IS NULL "
            "AND last_tested_at IS NOT NULL) "
            "OR (last_test_status = 'failed' "
            "AND last_test_error_code IS NOT NULL "
            "AND last_tested_at IS NOT NULL)",
            name="ck_email_settings_test_state",
        ),
    )


class AdministratorSummaryDelivery(Base):
    """Canonical automated-delivery state for one reporting window."""

    __tablename__ = "administrator_summary_delivery"

    administrator_summary_delivery_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    period_start: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    cadence: Mapped[str] = mapped_column(String(32), nullable=False)
    reporting_timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_attempted_at: Mapped[Optional["DateTime"]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[Optional["DateTime"]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped["DateTime"] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "period_start",
            "period_end",
            name="uq_administrator_summary_delivery_period",
        ),
        CheckConstraint(
            "period_start < period_end",
            name="ck_administrator_summary_delivery_period",
        ),
        CheckConstraint(
            "cadence IN ('daily', 'hourly', 'every_15_minutes')",
            name="ck_administrator_summary_delivery_cadence",
        ),
        CheckConstraint(
            "status IN ('sending', 'sent', 'failed', 'delivery_unknown')",
            name="ck_administrator_summary_delivery_status",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 2",
            name="ck_administrator_summary_delivery_attempt_count",
        ),
    )
