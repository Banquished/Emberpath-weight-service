from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from src.models.user import User
from src.models.weight_goal import WeightGoal
from src.routers.weight_goals import set_active_goal
from src.schemas.weight_goal import WeightGoalSet

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
PAYLOAD = {
    "target_weight_kg": 95,
    "baseline_weight_kg": 100,
    "start_date": "2026-09-21",
    "target_date": "2027-01-01",
}


@pytest.mark.parametrize("status", ["completed", "cancelled"])
async def test_goal_lifecycle(client: AsyncClient, status: str):
    assert (await client.get("/weight-goals/active")).json() is None
    response = await client.put("/weight-goals/active", json=PAYLOAD)
    assert response.status_code == 200
    goal = response.json()
    assert UUID(goal["id"])
    assert goal["status"] == "active"
    assert goal["ended_at"] is None
    assert goal["target_weight_kg"] == 95
    assert (await client.put("/weight-goals/active", json=PAYLOAD)).json() == goal
    assert (await client.get("/weight-goals/active")).json() == goal
    response = await client.patch(
        f"/weight-goals/{goal['id']}", json={"status": status}
    )
    assert response.status_code == 200
    assert response.json()["status"] == status
    assert response.json()["ended_at"] is not None
    assert (await client.get("/weight-goals/active")).json() is None
    assert (
        await client.patch(f"/weight-goals/{goal['id']}", json={"status": status})
    ).status_code == 409
    assert (await client.put("/weight-goals/active", json=PAYLOAD)).json()[
        "id"
    ] != goal["id"]


async def test_replacement_and_user_isolation(client: AsyncClient):
    first = (await client.put("/weight-goals/active", json=PAYLOAD)).json()
    other = {"X-Test-Subject": "other-user"}
    assert (await client.get("/weight-goals/active", headers=other)).json() is None
    assert (
        await client.patch(
            f"/weight-goals/{first['id']}", json={"status": "completed"}, headers=other
        )
    ).status_code == 404
    other_goal = (
        await client.put("/weight-goals/active", json=PAYLOAD, headers=other)
    ).json()
    replacement = (
        await client.put(
            "/weight-goals/active", json={**PAYLOAD, "target_weight_kg": 90}
        )
    ).json()
    assert replacement["id"] != first["id"]
    assert (await client.get("/weight-goals/active")).json() == replacement
    assert (
        await client.get("/weight-goals/active", headers=other)
    ).json() == other_goal
    assert (
        await client.patch(f"/weight-goals/{first['id']}", json={"status": "completed"})
    ).status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        {"target_weight_kg": 0},
        {"target_weight_kg": -1},
        {"target_weight_kg": 10000},
        {"target_weight_kg": 90.123},
        {"target_weight_kg": "NaN"},
        {"target_weight_kg": None},
        {"start_date": None},
        {"target_date": "2026-09-20"},
        {"target_date": "2026-09-21"},
        {"baseline_weight_kg": 0},
        {"baseline_weight_kg": 100.123},
        {"target_date": "not-a-date"},
        {"user_id": str(uuid4())},
        {"status": "completed"},
    ],
)
async def test_invalid_goal_leaves_active_goal_unchanged(
    client: AsyncClient, changes: dict
):
    goal = (await client.put("/weight-goals/active", json=PAYLOAD)).json()
    assert (
        await client.put("/weight-goals/active", json={**PAYLOAD, **changes})
    ).status_code == 422
    assert (await client.get("/weight-goals/active")).json() == goal


async def test_optional_target_date_and_invalid_end(client: AsyncClient):
    response = await client.put(
        "/weight-goals/active",
        json={"target_weight_kg": 95.25, "start_date": "2026-09-21"},
    )
    assert response.status_code == 200
    goal = response.json()
    assert goal["target_date"] is None
    for payload in [
        {},
        {"status": "active"},
        {"status": "replaced"},
        {"status": "completed", "target_weight_kg": 90},
    ]:
        assert (
            await client.patch(f"/weight-goals/{goal['id']}", json=payload)
        ).status_code == 422
    assert (
        await client.patch(f"/weight-goals/{uuid4()}", json={"status": "completed"})
    ).status_code == 404


def test_database_enforces_one_active_goal_and_preserves_history(test_database_url):
    engine = create_engine(test_database_url, hide_parameters=True)
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            with Session(
                connection, join_transaction_mode="create_savepoint"
            ) as session:
                owner = User()
                session.add(owner)
                session.flush()

                def make_goal():
                    return WeightGoal(
                        user_id=owner.id,
                        target_weight_kg=Decimal("95"),
                        start_date=datetime.now(UTC).date(),
                        status="active",
                        created_at=datetime.now(UTC),
                    )

                first = make_goal()
                session.add(first)
                session.flush()
                with pytest.raises(IntegrityError), session.begin_nested():
                    session.add(make_goal())
                    session.flush()
                first.status = "replaced"
                first.ended_at = datetime.now(UTC)
                session.flush()
                session.add(make_goal())
                session.flush()
                goals = list(
                    session.scalars(
                        select(WeightGoal).where(WeightGoal.user_id == owner.id)
                    )
                )
                assert {g.status for g in goals} == {"active", "replaced"}
                assert len(goals) == 2
            transaction.rollback()
    finally:
        engine.dispose()


async def test_replacement_retains_history_and_identical_put_does_not(
    test_database_url,
):
    engine = create_async_engine(test_database_url, hide_parameters=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(
                    connection,
                    join_transaction_mode="create_savepoint",
                    expire_on_commit=False,
                ) as session:
                    owner = User()
                    session.add(owner)
                    await session.flush()
                    payload = WeightGoalSet.model_validate(PAYLOAD)
                    first = await set_active_goal(payload, owner.id, session)
                    same = await set_active_goal(payload, owner.id, session)
                    assert same.id == first.id
                    replacement = await set_active_goal(
                        payload.model_copy(update={"target_weight_kg": Decimal("90")}),
                        owner.id,
                        session,
                    )
                    await session.refresh(first)
                    assert first.status == "replaced"
                    assert first.ended_at == replacement.created_at
                    goals = list(
                        await session.scalars(
                            select(WeightGoal).where(WeightGoal.user_id == owner.id)
                        )
                    )
                    assert len(goals) == 2
                    assert replacement.status == "active"
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "target,weekly,fortnightly", [(95, -0.5, -1), (105, 0.5, 1), (100, 0, 0)]
)
async def test_goal_plan_arithmetic(client: AsyncClient, target, weekly, fortnightly):
    response = await client.put(
        "/weight-goals/active",
        json={
            **PAYLOAD,
            "target_weight_kg": target,
            "target_date": "2026-11-30",
        },
    )
    assert response.status_code == 200
    assert response.json()["baseline_weight_kg"] == 100
    assert response.json()["plan"] == {
        "duration_days": 70,
        "total_change_kg": target - 100,
        "weekly_change_kg": weekly,
        "fortnightly_change_kg": fortnightly,
    }


async def test_baseline_is_user_scoped_as_of_start_and_remains_snapshot(
    client: AsyncClient,
):
    for day, weight, headers in [
        ("2026-09-19", 105, {}),
        ("2026-09-20", 100, {}),
        ("2026-09-21", 60, {"X-Test-Subject": "other-user"}),
        ("2026-09-22", 110, {}),
    ]:
        response = await client.post(
            "/weight-logs", json={"date": day, "weight_kg": weight}, headers=headers
        )
        assert response.status_code == 201
    payload = {**PAYLOAD, "baseline_weight_kg": None}
    response = await client.put("/weight-goals/active", json=payload)
    assert response.status_code == 200
    first = response.json()
    assert first["baseline_weight_kg"] == 100
    assert (
        await client.post("/weight-logs", json={"date": "2026-09-21", "weight_kg": 102})
    ).status_code == 201
    assert (await client.get("/weight-goals/active")).json() == first
    assert (await client.put("/weight-goals/active", json=payload)).json() == first
    updated = await client.put(
        "/weight-goals/active", json={**payload, "baseline_weight_kg": 103}
    )
    assert updated.json()["baseline_weight_kg"] == 103
    assert updated.json()["id"] != first["id"]


async def test_missing_baseline_is_actionable_and_undated_goal_still_works(
    client: AsyncClient,
):
    payload = {k: v for k, v in PAYLOAD.items() if k != "baseline_weight_kg"}
    response = await client.put("/weight-goals/active", json=payload)
    assert response.status_code == 422
    assert "starting weight" in response.text
    response = await client.put(
        "/weight-goals/active", json={**payload, "target_date": None}
    )
    assert response.status_code == 200
    assert response.json()["baseline_weight_kg"] is None
    assert response.json()["plan"] is None
    current = response.json()
    assert (await client.put("/weight-goals/active", json=payload)).status_code == 422
    assert (await client.get("/weight-goals/active")).json() == current
    response = await client.put(
        "/weight-goals/active", json={**payload, "baseline_weight_kg": 99}
    )
    assert response.status_code == 200
    assert response.json()["plan"]["total_change_kg"] == -4
