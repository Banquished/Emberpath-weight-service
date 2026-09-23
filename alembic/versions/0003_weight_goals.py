"""Add user-owned weight goals without changing measurements."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weight_goals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_weight_kg", sa.Numeric(6, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "target_weight_kg > 0", name="ck_weight_goals_positive_weight"
        ),
        sa.CheckConstraint(
            "target_date IS NULL OR target_date >= start_date",
            name="ck_weight_goals_dates",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'cancelled', 'replaced')",
            name="ck_weight_goals_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND ended_at IS NULL) OR (status <> 'active' AND ended_at IS NOT NULL)",
            name="ck_weight_goals_ended_at",
        ),
    )
    op.create_index(
        "uq_weight_goals_active_user",
        "weight_goals",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("weight_goals")
