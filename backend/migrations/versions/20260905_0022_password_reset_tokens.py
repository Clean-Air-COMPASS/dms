"""Store only hashes of administrator-issued password reset tokens."""
from alembic import op
import sqlalchemy as sa

revision = "20260905_0022"
down_revision = "20260905_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_reset_token",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("user.user_id", ondelete="SET NULL")),
    )
    op.create_index("ix_password_reset_token_user_id", "password_reset_token", ["user_id"])


def downgrade():
    op.drop_table("password_reset_token")
