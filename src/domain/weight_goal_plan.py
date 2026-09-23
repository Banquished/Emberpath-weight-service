from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.domain.weight_summary import rounded


@dataclass(frozen=True)
class GoalPlan:
    duration_days: int
    total_change_kg: Decimal
    weekly_change_kg: Decimal
    fortnightly_change_kg: Decimal


def calculate_goal_plan(
    baseline_weight_kg: Decimal | None,
    target_weight_kg: Decimal,
    start_date: date,
    target_date: date | None,
) -> GoalPlan | None:
    if baseline_weight_kg is None or target_date is None:
        return None
    duration = (target_date - start_date).days
    if duration <= 0:
        return None
    change = target_weight_kg - baseline_weight_kg
    return GoalPlan(
        duration_days=duration,
        total_change_kg=rounded(change),
        weekly_change_kg=rounded(change * 7 / duration),
        fortnightly_change_kg=rounded(change * 14 / duration),
    )
