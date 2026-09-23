from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.config import Settings
from src.domain.weight_summary import rounded, summarize_weights
from src.main import create_app
from src.schemas.weight_log import WeightLogRead


def measurement(day: int, weight: str) -> WeightLogRead:
    return WeightLogRead(id=uuid4(), date=date(2026, 9, day), weight_kg=Decimal(weight))


def test_summary_empty_and_singleton():
    assert summarize_weights([]).model_dump() == {
        "measurement_count": 0,
        "mean_weight_kg": None,
        "first": None,
        "latest": None,
        "change_kg": None,
        "change_percent": None,
    }
    log = measurement(1, "80.25")
    summary = summarize_weights([log])
    assert summary.mean_weight_kg == Decimal("80.25")
    assert summary.first == summary.latest == log
    assert summary.change_kg is None
    assert summary.change_percent is None


@pytest.mark.parametrize(
    "start,end,mean,change,percent",
    [
        ("80", "79.99", "80.00", "-0.01", "-0.01"),
        ("80", "80.01", "80.01", "0.01", "0.01"),
        ("80", "80", "80.00", "0.00", "0.00"),
        ("200", "199.99", "200.00", "-0.01", "-0.01"),
    ],
)
def test_summary_decimal_rounding_and_chronology(start, end, mean, change, percent):
    first, latest = measurement(1, start), measurement(30, end)
    summary = summarize_weights([latest, first])
    assert summary.first == first
    assert summary.latest == latest
    assert summary.mean_weight_kg == Decimal(mean)
    assert summary.change_kg == Decimal(change)
    assert summary.change_percent == Decimal(percent)
    assert isinstance(summary.model_dump(mode="json")["mean_weight_kg"], float)


def test_summary_ignores_missing_days_and_normalizes_negative_zero():
    summary = summarize_weights(
        [
            measurement(1, "90"),
            measurement(2, "80"),
            measurement(30, "70"),
        ]
    )
    assert summary.mean_weight_kg == Decimal("80")
    assert summary.change_kg == Decimal("-20")
    assert summary.change_percent == Decimal("-22.22")
    assert str(rounded(Decimal("-0.001"))) == "0.00"


@pytest.mark.anyio
async def test_summary_requires_authentication():
    app = create_app(Settings(_env_file=None))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.get("/weight-logs/summary")
    assert response.status_code == 401


@pytest.mark.anyio
@pytest.mark.integration
async def test_summary_period_boundaries_and_ownership(client):
    logs = []
    for day, weight in [(1, 90), (10, 80), (20, 70), (30, 60)]:
        response = await client.post(
            "/weight-logs",
            json={
                "date": f"2026-09-{day:02d}",
                "weight_kg": weight,
            },
        )
        assert response.status_code == 201
        logs.append(response.json())
    response = await client.get(
        "/weight-logs/summary",
        params={
            "start_date": "2026-09-10",
            "end_date": "2026-09-20",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "measurement_count": 2,
        "mean_weight_kg": 75,
        "first": logs[1],
        "latest": logs[2],
        "change_kg": -10,
        "change_percent": -12.5,
    }
    assert (await client.get("/weight-logs/summary")).json()["measurement_count"] == 4
    assert (await client.get("/weight-logs/summary?start_date=2026-09-20")).json()[
        "measurement_count"
    ] == 2
    assert (await client.get("/weight-logs/summary?end_date=2026-09-10")).json()[
        "measurement_count"
    ] == 2
    singleton = (
        await client.get(
            "/weight-logs/summary?start_date=2026-09-30&end_date=2026-09-30"
        )
    ).json()
    assert singleton["first"] == singleton["latest"] == logs[3]
    assert singleton["change_kg"] is None
    client.headers["X-Test-Subject"] = "user_other"
    empty = (await client.get("/weight-logs/summary")).json()
    assert empty["measurement_count"] == 0
    assert all(
        value is None for key, value in empty.items() if key != "measurement_count"
    )
    other = await client.post(
        "/weight-logs", json={"date": "2026-09-10", "weight_kg": 50}
    )
    assert other.status_code == 201
    del client.headers["X-Test-Subject"]
    assert (await client.get("/weight-logs/summary")).json()["measurement_count"] == 4


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
async def test_summary_invalid_dates(client, query):
    assert (await client.get(f"/weight-logs/summary?{query}")).status_code == 422


@pytest.mark.anyio
@pytest.mark.integration
async def test_summary_excludes_unclaimed_measurements(client, test_database_url):
    from sqlalchemy import delete

    from src.core.database import Database
    from src.models.weight_log import WeightLog

    database = Database(Settings(database_url=test_database_url, _env_file=None))
    log_id = uuid4()
    try:
        async with database.session_factory() as session:
            session.add(
                WeightLog(id=log_id, date=date(2099, 1, 1), weight_kg=Decimal("100"))
            )
            await session.commit()
        assert (await client.get("/weight-logs/summary")).json()[
            "measurement_count"
        ] == 0
    finally:
        async with database.session_factory() as session:
            await session.execute(delete(WeightLog).where(WeightLog.id == log_id))
            await session.commit()
        await database.dispose()
