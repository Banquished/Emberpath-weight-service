from decimal import Decimal

from pydantic import BaseModel, field_serializer

from src.schemas.weight_log import WeightLogRead


class WeightSummary(BaseModel):
    measurement_count: int
    mean_weight_kg: Decimal | None
    first: WeightLogRead | None
    latest: WeightLogRead | None
    change_kg: Decimal | None
    change_percent: Decimal | None

    @field_serializer("mean_weight_kg", "change_kg", "change_percent")
    def serialize_decimal(self, value: Decimal | None) -> float | None:
        return float(value) if value is not None else None
