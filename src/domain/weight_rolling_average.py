from collections import deque
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from src.domain.weight_summary import rounded
from src.schemas.weight_log import WeightLogRead
from src.schemas.weight_rolling_average import (
    RollingAveragePoint,
    RollingAverageWindow,
    WeightRollingAverage,
)


def rolling_average(
    logs: Sequence[WeightLogRead],
    start_date: date | None = None,
    window_days: RollingAverageWindow = RollingAverageWindow.WEEK,
) -> WeightRollingAverage:
    window: deque[WeightLogRead] = deque()
    total = Decimal(0)
    points: list[RollingAveragePoint] = []
    for log in sorted(logs, key=lambda item: item.date):
        while window and (log.date - window[0].date).days >= window_days:
            total -= window.popleft().weight_kg
        window.append(log)
        total += log.weight_kg
        if start_date is None or log.date >= start_date:
            points.append(
                RollingAveragePoint(
                    date=log.date,
                    mean_weight_kg=rounded(total / len(window)),
                    measurement_count=len(window),
                )
            )
    return WeightRollingAverage(window_days=window_days, points=points)
