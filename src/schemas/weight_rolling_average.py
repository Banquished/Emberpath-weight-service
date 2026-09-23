from datetime import date
from decimal import Decimal
from enum import IntEnum

from pydantic import BaseModel, field_serializer


class RollingAverageWindow(IntEnum):
    WEEK = 7
    FORTNIGHT = 14
    MONTH = 30


class RollingAveragePoint(BaseModel):
    date: date
    mean_weight_kg: Decimal
    measurement_count: int

    @field_serializer("mean_weight_kg")
    def serialize_decimal(self, value: Decimal) -> float:
        return float(value)


class WeightRollingAverage(BaseModel):
    window_days: RollingAverageWindow = RollingAverageWindow.WEEK
    points: list[RollingAveragePoint]
