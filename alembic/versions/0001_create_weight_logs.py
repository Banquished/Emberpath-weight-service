"""Create weight logs."""

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weight_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_weight_logs_date"),
        sa.CheckConstraint("weight_kg > 0", name="ck_weight_logs_positive_weight"),
    )


def downgrade() -> None:
    op.drop_table("weight_logs")
