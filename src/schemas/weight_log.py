from datetime import date as Date
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

WeightKg = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]


class WeightLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: Date
    weight_kg: WeightKg


class WeightLogUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: Date | None = None
    weight_kg: WeightKg | None = None

    @field_validator("date", "weight_kg")
    @classmethod
    def reject_null(cls, value: Date | Decimal | None) -> Date | Decimal:
        if value is None:
            raise ValueError("Field cannot be null")
        return value

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class WeightLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    date: Date
    weight_kg: Decimal

    @field_serializer("weight_kg")
    def serialize_weight(self, value: Decimal) -> float:
        return float(value)
