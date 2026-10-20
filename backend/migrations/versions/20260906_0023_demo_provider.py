"""Offline Demo source with installation-aware defaults and durable seed state."""
from alembic import op
import sqlalchemy as sa

revision = "20260906_0023"
down_revision = "20260905_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_import_state",
        sa.Column("external_api_id", sa.Integer(), sa.ForeignKey("external_api.external_api_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("initial_seed_pending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Unknown/offline migration context is conservative. Only an online run
    # starting without any installed revision qualifies for default-on.
    new_install = op.get_context().config.attributes.get("is_new_installation", False)
    enabled = "true" if new_install else "false"
    op.execute(sa.text(f"""
        INSERT INTO external_api (provider_code, name, description, params, enabled)
        VALUES ('demo', 'Demo Data',
          'Clearly fake air-quality observations from an offline demonstration fixture. Not a real monitoring location.',
          '{{}}', {enabled})
        ON CONFLICT (provider_code) DO NOTHING
    """))
    op.execute(sa.text(f"""
        INSERT INTO demo_import_state (external_api_id, initial_seed_pending)
        SELECT external_api_id, {enabled} FROM external_api WHERE provider_code = 'demo'
    """))
    op.execute(sa.text("""
        INSERT INTO job_schedule (task, cron_expr, timezone, enabled, allow_overlap)
        VALUES ('demo_import', '*/5 * * * *', 'UTC', true, false)
    """))
    op.execute(sa.text("""
        INSERT INTO aggregation_period (code, display_name, duration_minutes, is_rolling, expected_interval)
        VALUES ('5m', '5-minute average', 5, false, '00:05:00')
        ON CONFLICT (code) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO parameter_aggregation_rollup
            (parameter_id, from_aggregation_period_id, to_aggregation_period_id)
        SELECT p.parameter_id, f.aggregation_period_id, t.aggregation_period_id
        FROM parameter p CROSS JOIN aggregation_period f CROSS JOIN aggregation_period t
        WHERE p.code IN ('pm25', 'pm10', 'o3') AND f.code = '5m' AND t.code = '1h'
        ON CONFLICT DO NOTHING
    """))


def downgrade() -> None:
    # Preserve source identity, observations and activation history. Removing
    # the latter would allow a later upgrade to repeat the initial seed.
    raise RuntimeError("Demo migration cannot be downgraded without losing durable activation state; restore a pre-upgrade backup instead.")
