"""preserve explicit Baseline Drift rules when defaults become disabled

Revision ID: 20260827_0015
Revises: 20260827_0014
Create Date: 2026-08-27

Baseline Drift originally shipped enabled in profile 2026.2. An existing
administrator rule with a sparse ``enabled_override`` therefore inherited On.
The profile now ships disabled, so this migration records On explicitly for
those existing rules and preserves their operational behavior. Explicitly
disabled rules remain disabled. Fresh installations have no rows to update.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260827_0015"
down_revision: Union[str, None] = "20260827_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE qc_rule SET enabled_override = true "
            "WHERE check_code = 'baseline_drift' "
            "AND enabled_override IS NULL"
        )
    )


def downgrade() -> None:
    # Keep the explicit enabled state. It is not possible to distinguish a
    # value written by this migration from an administrator's explicit value,
    # and clearing either could silently disable a configured production rule.
    pass
