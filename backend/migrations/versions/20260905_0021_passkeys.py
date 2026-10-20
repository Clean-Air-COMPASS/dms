"""Store passkey public credentials and short-lived, single-use challenges."""
from alembic import op
import sqlalchemy as sa

revision = "20260905_0021"
down_revision = "20260905_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "passkey",
        sa.Column("credential_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("rp_id", sa.Text(), nullable=False),
    )
    op.create_index("ix_passkey_user_id", "passkey", ["user_id"])
    op.create_table(
        "passkey_challenge",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("challenge", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.user_id", ondelete="CASCADE")),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_passkey_challenge_expires_at", "passkey_challenge", ["expires_at"])


def downgrade():
    op.drop_table("passkey_challenge")
    op.drop_table("passkey")
