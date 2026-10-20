"""repair persisted setup state and default language

Revision ID: 20260902_0017
Revises: 20260827_0016
Create Date: 2026-09-02

The persisted ``is_system_setup_complete`` field remains the authoritative
installation state. This migration repairs the known development/test-harness
failure mode only when the database contains strong evidence that first-run
setup had already produced an operational installation: an active
administrator and imported measurements. A setup that has only created its
initial administrator remains incomplete.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260902_0017"
down_revision: str | None = "20260827_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A test process connected to a deployment database could delete the
    # singleton outright. Recreate the persisted marker before evaluating the
    # configured-installation evidence below. The normal fresh migration path
    # already has this row from the initial schema migration.
    op.execute(
        sa.text(
            """
            INSERT INTO system_settings (
                is_system_setup_complete,
                default_language_code,
                system_timezone
            )
            SELECT false, 'en', 'UTC'
            WHERE NOT EXISTS (SELECT 1 FROM system_settings)
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE system_settings
            SET is_system_setup_complete = true
            WHERE is_system_setup_complete = false
              AND EXISTS (
                  SELECT 1
                  FROM "user" AS platform_user
                  JOIN user_role
                    ON user_role.user_id = platform_user.user_id
                  JOIN role
                    ON role.role_id = user_role.role_id
                  WHERE platform_user.is_active = true
                    AND role.name = 'admin'
              )
              AND EXISTS (
                  SELECT 1
                  FROM measurement
              )
            """
        )
    )

    # Language is a display preference, not evidence of installation state.
    # Existing NULL values receive the safe product default independently.
    op.execute(
        sa.text(
            "UPDATE system_settings "
            "SET default_language_code = 'en' "
            "WHERE default_language_code IS NULL"
        )
    )
    op.alter_column(
        "system_settings",
        "default_language_code",
        existing_type=sa.String(length=2),
        nullable=True,
        server_default=sa.text("'en'"),
    )


def downgrade() -> None:
    # Do not revert repaired setup completion: the prior false value was the
    # corruption this migration exists to correct.
    op.alter_column(
        "system_settings",
        "default_language_code",
        existing_type=sa.String(length=2),
        nullable=True,
        server_default=None,
    )
