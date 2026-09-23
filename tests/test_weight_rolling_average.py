from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.config import Settings
from src.domain.weight_rolling_average import rolling_average
from src.main import create_app
from src.schemas.weight_log import WeightLogRead


def measurement(day, weight):
    return WeightLogRead(id=uuid4(), date=date(2026, 9, day), weight_kg=Decimal(weight))


def test_empty_and_singleton():
    assert rolling_average([]).model_dump() == {"window_days": 7, "points": []}
    result = rolling_average([measurement(1, "80.25")]).model_dump(mode="json")
    assert result == {
        "window_days": 7,
        "points": [
            {"date": "2026-09-01", "mean_weight_kg": 80.25, "measurement_count": 1}
        ],
    }


def test_calendar_windows_boundaries_gaps_and_no_lookahead():
    logs = [
        measurement(day, weight)
        for day, weight in [(1, "100"), (2, "90"), (7, "80"), (8, "70"), (30, "60")]
    ]
    result = rolling_average(list(reversed(logs)))
    assert [
        (p.date.day, p.mean_weight_kg, p.measurement_count) for p in result.points
    ] == [
        (1, Decimal("100"), 1),
        (2, Decimal("95"), 2),
        (7, Decimal("90"), 3),
        (8, Decimal("80"), 3),
        (30, Decimal("60"), 1),
    ]


def test_output_filter_preserves_lookback_and_half_up_rounding():
    result = rolling_average(
        [measurement(1, "80"), measurement(7, "80.01")], date(2026, 9, 7)
    )
    assert len(result.points) == 1
    assert result.points[0].mean_weight_kg == Decimal("80.01")
    assert result.points[0].measurement_count == 2
    assert rolling_average([measurement(1, "80")], date(2026, 9, 2)).points == []


@pytest.mark.anyio
async def test_requires_authentication():
    app = create_app(Settings(_env_file=None))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (await http.get("/weight-logs/rolling-average")).status_code == 401


@pytest.mark.anyio
@pytest.mark.integration
async def test_period_lookback_boundaries_and_ownership(client):
    for day, weight in [(1, 100), (2, 90), (7, 80), (8, 70), (30, 60)]:
        response = await client.post(
            "/weight-logs", json={"date": f"2026-09-{day:02d}", "weight_kg": weight}
        )
        assert response.status_code == 201
    response = await client.get(
        "/weight-logs/rolling-average?start_date=2026-09-07&end_date=2026-09-08"
    )
    assert response.status_code == 200
    assert response.json() == {
        "window_days": 7,
        "points": [
            {"date": "2026-09-07", "mean_weight_kg": 90, "measurement_count": 3},
            {"date": "2026-09-08", "mean_weight_kg": 80, "measurement_count": 3},
        ],
    }
    all_points = (await client.get("/weight-logs/rolling-average")).json()["points"]
    assert len(all_points) == 5
    assert (
        await client.get("/weight-logs/rolling-average?end_date=2026-09-07")
    ).json()["points"] == all_points[:3]
    assert (
        await client.get("/weight-logs/rolling-average?start_date=2026-09-07")
    ).json()["points"] == all_points[2:]
    assert (
        await client.get(
            "/weight-logs/rolling-average?start_date=2026-09-09&end_date=2026-09-29"
        )
    ).json()["points"] == []
    client.headers["X-Test-Subject"] = "user_other"
    assert (await client.get("/weight-logs/rolling-average")).json()["points"] == []
    assert (
        await client.post("/weight-logs", json={"date": "2026-09-07", "weight_kg": 50})
    ).status_code == 201
    assert (await client.get("/weight-logs/rolling-average")).json()["points"] == [
        {"date": "2026-09-07", "mean_weight_kg": 50, "measurement_count": 1},
    ]
    del client.headers["X-Test-Subject"]
    assert (await client.get("/weight-logs/rolling-average")).json()[
        "points"
    ] == all_points


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize("window_days", [7, 14, 30])
async def test_minimum_date_lookback_is_clamped(client, window_days):
    response = await client.post(
        "/weight-logs", json={"date": "0001-01-01", "weight_kg": 80}
    )
    assert response.status_code == 201
    response = await client.get(
        "/weight-logs/rolling-average?start_date=0001-01-01&end_date=0001-01-01"
        f"&window_days={window_days}"
    )
    assert response.status_code == 200
    assert response.json()["points"] == [
        {"date": "0001-01-01", "mean_weight_kg": 80, "measurement_count": 1}
    ]


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize(
    "query",
    [
        "start_date=invalid",
        "end_date=2026-02-30",
        "start_date=2026-09-20&end_date=2026-09-01",
    ],
)
async def test_invalid_dates(client, query):
    assert (
        await client.get(f"/weight-logs/rolling-average?{query}")
    ).status_code == 422


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize("window_days", [7, 14, 30])
async def test_configurable_windows_boundaries_range_invariance_and_ownership(
    client, window_days
):
    point_date = date(2026, 9, 30)
    logs = [
        (point_date - timedelta(days=window_days), 100),
        (point_date - timedelta(days=window_days - 1), 90),
        (point_date, 80),
        (point_date + timedelta(days=1), 70),
        (point_date + timedelta(days=window_days + 1), 60),
    ]
    for log_date, weight in logs:
        assert (
            await client.post(
                "/weight-logs", json={"date": log_date.isoformat(), "weight_kg": weight}
            )
        ).status_code == 201
    endpoint = f"/weight-logs/rolling-average?window_days={window_days}"
    response = await client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {
        "window_days": window_days,
        "points": [
            {
                "date": logs[0][0].isoformat(),
                "mean_weight_kg": 100,
                "measurement_count": 1,
            },
            {
                "date": logs[1][0].isoformat(),
                "mean_weight_kg": 95,
                "measurement_count": 2,
            },
            {
                "date": point_date.isoformat(),
                "mean_weight_kg": 85,
                "measurement_count": 2,
            },
            {
                "date": logs[3][0].isoformat(),
                "mean_weight_kg": 75,
                "measurement_count": 2,
            },
            {
                "date": logs[4][0].isoformat(),
                "mean_weight_kg": 60,
                "measurement_count": 1,
            },
        ],
    }
    filtered = await client.get(
        endpoint + f"&start_date={point_date}&end_date={point_date}"
    )
    assert filtered.status_code == 200
    assert filtered.json() == {
        "window_days": window_days,
        "points": response.json()["points"][2:3],
    }
    client.headers["X-Test-Subject"] = "user_other"
    assert (await client.get(endpoint)).json() == {
        "window_days": window_days,
        "points": [],
    }
    assert (
        await client.post(
            "/weight-logs", json={"date": point_date.isoformat(), "weight_kg": 50}
        )
    ).status_code == 201
    assert (await client.get(endpoint)).json()["points"] == [
        {"date": point_date.isoformat(), "mean_weight_kg": 50, "measurement_count": 1}
    ]
    del client.headers["X-Test-Subject"]
    assert (await client.get(endpoint)).json() == response.json()


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize(
    "window_days", ["0", "-7", "1", "8", "15", "31", "7.5", "abc", ""]
)
async def test_unsupported_window_returns_422(client, window_days):
    response = await client.get(
        f"/weight-logs/rolling-average?window_days={window_days}"
    )
    assert response.status_code == 422
