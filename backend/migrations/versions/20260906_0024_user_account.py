"""Self-service profile, passkey metadata, recent authentication and audit names."""
from alembic import op
import sqlalchemy as sa

revision = "20260906_0024"
down_revision = "20260906_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("user", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column("passkey", sa.Column("name", sa.String(100), nullable=True))
    op.add_column("passkey", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("passkey", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("event", sa.Column("actor_display_name", sa.String(320), nullable=True))
    op.create_table(
        "reauthentication_grant",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("access_token_jti", sa.Uuid(), nullable=False),
        sa.Column("authentication_state", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_reauthentication_grant_user_id", "reauthentication_grant", ["user_id"])
    op.create_index("ix_reauthentication_grant_expires_at", "reauthentication_grant", ["expires_at"])


def downgrade():
    op.drop_table("reauthentication_grant")
    op.drop_column("event", "actor_display_name")
    op.drop_column("passkey", "last_used_at")
    op.drop_column("passkey", "created_at")
    op.drop_column("passkey", "name")
    op.drop_column("user", "last_name")
    op.drop_column("user", "first_name")
