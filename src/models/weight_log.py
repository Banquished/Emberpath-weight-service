from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class WeightLog(Base):
    __tablename__ = "weight_logs"
    __table_args__ = (
        UniqueConstraint("date", name="uq_weight_logs_date"),
        CheckConstraint("weight_kg > 0", name="ck_weight_logs_positive_weight"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    date: Mapped[date]
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
