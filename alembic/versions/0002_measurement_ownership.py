"""Add user identity and measurement ownership without claiming legacy data."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("users", sa.Column("id", sa.Uuid(), primary_key=True))
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity"),
    )
    op.create_index(
        "ix_external_identities_user_id", "external_identities", ["user_id"]
    )
    op.add_column("weight_logs", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_weight_logs_user_id", "weight_logs", "users", ["user_id"], ["id"]
    )
    op.drop_constraint("uq_weight_logs_date", "weight_logs", type_="unique")
    op.create_unique_constraint(
        "uq_weight_logs_user_date", "weight_logs", ["user_id", "date"]
    )


def downgrade() -> None:
    # This intentionally fails atomically if multiple users now share a date.
    op.create_unique_constraint("uq_weight_logs_date", "weight_logs", ["date"])
    op.drop_constraint("uq_weight_logs_user_date", "weight_logs", type_="unique")
    op.drop_column("weight_logs", "user_id")
    op.drop_table("external_identities")
    op.drop_table("users")
