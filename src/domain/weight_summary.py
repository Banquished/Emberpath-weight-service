from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from src.schemas.weight_log import WeightLogRead
from src.schemas.weight_summary import WeightSummary


def rounded(value: Decimal) -> Decimal:
    result = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return abs(result) if result == 0 else result


def summarize_weights(logs: Sequence[WeightLogRead]) -> WeightSummary:
    if not logs:
        return WeightSummary(
            measurement_count=0,
            mean_weight_kg=None,
            first=None,
            latest=None,
            change_kg=None,
            change_percent=None,
        )
    first = min(logs, key=lambda log: log.date)
    latest = max(logs, key=lambda log: log.date)
    change = latest.weight_kg - first.weight_kg if len(logs) > 1 else None
    return WeightSummary(
        measurement_count=len(logs),
        mean_weight_kg=rounded(
            sum((log.weight_kg for log in logs), Decimal(0)) / len(logs)
        ),
        first=first,
        latest=latest,
        change_kg=rounded(change) if change is not None else None,
        change_percent=(
            rounded(change / first.weight_kg * 100) if change is not None else None
        ),
    )
