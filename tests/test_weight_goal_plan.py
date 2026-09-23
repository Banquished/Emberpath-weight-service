from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.domain.weight_goal_plan import calculate_goal_plan
from src.schemas.weight_goal import WeightGoalRead


@pytest.mark.parametrize(
    "baseline,target_date",
    [
        (None, date(2026, 2, 1)),
        (Decimal("100"), None),
        (Decimal("100"), date(2026, 1, 1)),
    ],
)
def test_legacy_and_undated_goals_have_no_plan(baseline, target_date):
    goal = WeightGoalRead(
        id=uuid4(),
        target_weight_kg=Decimal("95"),
        baseline_weight_kg=baseline,
        start_date=date(2026, 1, 1),
        target_date=target_date,
        status="active",
        created_at=datetime.now(UTC),
        ended_at=None,
    )
    assert goal.model_dump(mode="json")["plan"] is None


def test_rounding_half_up_and_calendar_days():
    plan = calculate_goal_plan(
        Decimal("100"), Decimal("99.99"), date(2026, 1, 1), date(2026, 1, 15)
    )
    assert plan is not None
    assert plan.duration_days == 14
    assert plan.weekly_change_kg == Decimal("-0.01")
    assert plan.fortnightly_change_kg == Decimal("-0.01")


def test_small_negative_change_rounds_to_positive_zero():
    plan = calculate_goal_plan(
        Decimal("100"), Decimal("99.99"), date(2026, 1, 1), date(2026, 12, 31)
    )
    assert plan is not None
    assert str(plan.weekly_change_kg) == "0.00"
