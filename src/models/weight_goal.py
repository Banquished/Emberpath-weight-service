from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class WeightGoal(Base):
    __tablename__ = "weight_goals"
    __table_args__ = (
        CheckConstraint("target_weight_kg > 0", name="ck_weight_goals_positive_weight"),
        CheckConstraint(
            "baseline_weight_kg IS NULL OR baseline_weight_kg > 0",
            name="ck_weight_goals_positive_baseline",
        ),
        CheckConstraint(
            "target_date IS NULL OR target_date >= start_date",
            name="ck_weight_goals_dates",
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'cancelled', 'replaced')",
            name="ck_weight_goals_status",
        ),
        CheckConstraint(
            "(status = 'active' AND ended_at IS NULL) OR (status <> 'active' AND ended_at IS NOT NULL)",
            name="ck_weight_goals_ended_at",
        ),
        Index(
            "uq_weight_goals_active_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    target_weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    baseline_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    start_date: Mapped[date]
    target_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
