"""Preserve an optional weight-goal starting baseline."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "weight_goals", sa.Column("baseline_weight_kg", sa.Numeric(6, 2), nullable=True)
    )
    op.create_check_constraint(
        "ck_weight_goals_positive_baseline",
        "weight_goals",
        "baseline_weight_kg IS NULL OR baseline_weight_kg > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_weight_goals_positive_baseline", "weight_goals", type_="check"
    )
    op.drop_column("weight_goals", "baseline_weight_kg")
