import uuid
from typing import Optional
from enum import Enum

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, Text, ForeignKey, DateTime, func, Float, Boolean, JSON, UniqueConstraint, Index, text
from sqlalchemy import select as select
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID


class Base(DeclarativeBase):
    pass


                            
class User(Base):
    __tablename__ = "user"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_failed_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    roles: Mapped[list["Role"]] = relationship(
        secondary="user_role",
        back_populates="users",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_user_email"),
        Index("ix_user_org_id", "org_id"),
    )


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
                                                                            
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
                                                                       
    external_api_id: Mapped[int] = mapped_column(ForeignKey("external_api.external_api_id", ondelete="RESTRICT"), nullable=False, index=True)
                                                                                                            
    manual_data_source_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
                                                                
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
                                                                                          
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
                                                                                   
                                                                             
    allow_updates: Mapped[UpdatePolicy] = mapped_column(
        SAEnum(UpdatePolicy, name="updatepolicy", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=UpdatePolicy.INHERIT.value,
    )
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sensors: Mapped[list["Sensor"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    locations: Mapped[list["DeviceLocationHistory"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        order_by="DeviceLocationHistory.effective_from"
    )
    external_api: Mapped["ExternalAPI"] = relationship(back_populates=None)


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
                                                                                 
    external_sensor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
                                                     
    allow_updates: Mapped[UpdatePolicy] = mapped_column(
        SAEnum(UpdatePolicy, name="updatepolicy", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        server_default=UpdatePolicy.INHERIT.value,
    )
    created_at:  Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="sensors")


class Measurement(Base):
    __tablename__ = "measurement"
    measurement_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
                                                                           
    api_key: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
                                                                       
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceLocationHistory(Base):
    __tablename__ = "device_location_history"
    device_location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("device.device_id", ondelete="CASCADE"), nullable=False, index=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    effective_from: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[Optional["DateTime"]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped[Device] = relationship(back_populates="locations")


                          

class JobStatus(Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


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
    started_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


                      

class QCRule(Base):
    __tablename__ = "qc_rule"
    qc_rule_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
                       
    check_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
                                                        
    sensor_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sensor.sensor_id", ondelete="CASCADE"), nullable=True, index=True)
    parameter_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("parameter.parameter_id", ondelete="CASCADE"), nullable=True, index=True)
    aggregate_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
                                                            
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")                         
    draft_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MeasurementQCResult(Base):
    __tablename__ = "measurement_qc_result"
    measurement_qc_result_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    measurement_id: Mapped[int] = mapped_column(Integer, ForeignKey("measurement.measurement_id", ondelete="CASCADE"), nullable=False, index=True)
    parameter_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("parameter.parameter_id", ondelete="SET NULL"), nullable=True, index=True)
    aggregate_code: Mapped[str] = mapped_column(String(32), nullable=False)
    check_code: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
                       
    severity: Mapped[str] = mapped_column(String(16), nullable=False, server_default="info")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    params_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plugin_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, server_default="ingest")
    qc_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("measurement_id", "check_code", name="uq_mqc_result_measurement_check"),
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
                                                                     
    is_system_setup_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
                                                                        
    geoapify_api_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
                
    created_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped["DateTime"] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
