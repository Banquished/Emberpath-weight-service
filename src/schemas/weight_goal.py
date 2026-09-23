from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    computed_field,
    field_serializer,
    model_validator,
)

from src.domain.weight_goal_plan import calculate_goal_plan
from src.schemas.weight_log import WeightKg


class WeightGoalSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_weight_kg: WeightKg
    start_date: date
    target_date: date | None = None
    baseline_weight_kg: WeightKg | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.target_date is not None and self.target_date <= self.start_date:
            raise ValueError("target_date must be after start_date")
        return self


class WeightGoalEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "cancelled"]


class WeightGoalPlan(BaseModel):
    duration_days: int
    total_change_kg: Decimal
    weekly_change_kg: Decimal
    fortnightly_change_kg: Decimal

    @field_serializer("total_change_kg", "weekly_change_kg", "fortnightly_change_kg")
    def serialize_change(self, value: Decimal) -> float:
        return float(value)


class WeightGoalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_weight_kg: Decimal
    baseline_weight_kg: Decimal | None
    start_date: date
    target_date: date | None
    status: Literal["active", "completed", "cancelled", "replaced"]
    created_at: datetime
    ended_at: datetime | None

    @field_serializer("target_weight_kg")
    def serialize_weight(self, value: Decimal) -> float:
        return float(value)

    @field_serializer("baseline_weight_kg")
    def serialize_baseline(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    @computed_field
    @property
    def plan(self) -> WeightGoalPlan | None:
        result = calculate_goal_plan(
            self.baseline_weight_kg,
            self.target_weight_kg,
            self.start_date,
            self.target_date,
        )
        return (
            WeightGoalPlan.model_validate(result, from_attributes=True)
            if result
            else None
        )
