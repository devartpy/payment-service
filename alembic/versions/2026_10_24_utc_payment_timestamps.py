"""Store payment and outbox timestamps with a UTC offset.

Revision ID: b7f4a9d20e61
Revises: c6a8be6e39c4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7f4a9d20e61"
down_revision: str | Sequence[str] | None = "c6a8be6e39c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Interpret existing naive timestamps as UTC before enabling time zones."""
    op.alter_column(
        "payments",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "payments",
        "processed_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=True,
        postgresql_using="processed_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "outbox_events",
        "created_at",
        existing_type=sa.DateTime(),
        type_=sa.DateTime(timezone=True),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )


def downgrade() -> None:
    """Convert UTC instants back to naive UTC timestamps."""
    op.alter_column(
        "outbox_events",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "payments",
        "processed_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=True,
        postgresql_using="processed_at AT TIME ZONE 'UTC'",
    )
    op.alter_column(
        "payments",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.DateTime(),
        existing_nullable=False,
        postgresql_using="created_at AT TIME ZONE 'UTC'",
    )
