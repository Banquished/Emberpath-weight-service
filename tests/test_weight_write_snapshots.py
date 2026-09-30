import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import get_current_user
from src.core.config import Settings
from src.core.database import Database
from src.main import create_app
from src.models.user import User
from src.models.weight_goal import WeightGoal
from src.models.weight_log import WeightLog

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

GOAL_PAYLOAD = {
    "target_weight_kg": 95,
    "baseline_weight_kg": 100,
    "start_date": "2026-09-21",
    "target_date": "2027-01-01",
}


@pytest.fixture
async def committed_client(
    test_database_url: str,
) -> AsyncIterator[tuple[AsyncClient, Database, UUID]]:
    app = create_app(
        Settings(database_url=test_database_url, database_required=True, _env_file=None)
    )
    database: Database = app.state.database
    async with app.router.lifespan_context(app):
        async with database.session_factory() as session:
            user = User()
            session.add(user)
            await session.commit()
            user_id = user.id

        app.dependency_overrides[get_current_user] = lambda: user_id
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                yield client, database, user_id
        finally:
            app.dependency_overrides.clear()
            async with database.session_factory() as session:
                await session.execute(
                    delete(WeightGoal).where(WeightGoal.user_id == user_id)
                )
                await session.execute(
                    delete(WeightLog).where(WeightLog.user_id == user_id)
                )
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()


async def interleave_commits(
    monkeypatch: pytest.MonkeyPatch,
    first: Callable[[], Awaitable[Response]],
    second: Callable[[], Awaitable[Response]],
) -> tuple[Response, Response]:
    first_committed = asyncio.Event()
    resume_first = asyncio.Event()
    original_commit = AsyncSession.commit
    first_task: asyncio.Task[Response] | None = None
    first_session: AsyncSession | None = None
    second_session: AsyncSession | None = None

    async def commit_with_barrier(session: AsyncSession) -> None:
        nonlocal first_session, second_session
        await original_commit(session)
        if asyncio.current_task() is first_task:
            first_session = session
            first_committed.set()
            await resume_first.wait()
        else:
            second_session = session

    with monkeypatch.context() as patched:
        patched.setattr(AsyncSession, "commit", commit_with_barrier)
        async with asyncio.TaskGroup() as group:
            first_task = group.create_task(first())
            try:
                async with asyncio.timeout(15):
                    await first_committed.wait()
                    second_response = await second()
            finally:
                resume_first.set()

    assert first_task is not None
    assert first_session is not None
    assert second_session is not None and second_session is not first_session
    return first_task.result(), second_response


async def test_create_ack_is_unchanged_by_later_edit(
    committed_client: tuple[AsyncClient, Database, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = committed_client

    async def edit_committed_log() -> Response:
        current = await client.get("/weight-logs")
        assert current.status_code == 200
        assert len(current.json()) == 1
        assert current.json()[0]["weight_kg"] == 80.25
        return await client.patch(
            f"/weight-logs/{current.json()[0]['id']}", json={"weight_kg": 79.75}
        )

    created, edited = await interleave_commits(
        monkeypatch,
        lambda: client.post(
            "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80.25}
        ),
        edit_committed_log,
    )
    assert created.status_code == 201
    assert edited.status_code == 200
    assert created.json() == {
        "id": edited.json()["id"],
        "date": "2026-09-17",
        "weight_kg": 80.25,
    }
    assert (await client.get(f"/weight-logs/{created.json()['id']}")).json() == (
        edited.json()
    )


@pytest.mark.parametrize("second_action", ["update", "delete"])
async def test_update_ack_survives_later_update_or_delete(
    committed_client: tuple[AsyncClient, Database, UUID],
    monkeypatch: pytest.MonkeyPatch,
    second_action: str,
) -> None:
    client, _, _ = committed_client
    original = (
        await client.post(
            "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80.25}
        )
    ).json()
    url = f"/weight-logs/{original['id']}"

    async def later_write() -> Response:
        if second_action == "delete":
            return await client.delete(url)
        return await client.patch(url, json={"weight_kg": 79.75})

    updated, later = await interleave_commits(
        monkeypatch,
        lambda: client.patch(url, json={"date": "2026-09-18", "weight_kg": 81.25}),
        later_write,
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "id": original["id"],
        "date": "2026-09-18",
        "weight_kg": 81.25,
    }
    current = await client.get(url)
    if second_action == "delete":
        assert later.status_code == 204
        assert current.status_code == 404
        assert current.json() == {"detail": "Weight log not found"}
    else:
        assert later.status_code == 200
        assert later.json() == {
            "id": original["id"],
            "date": "2026-09-18",
            "weight_kg": 79.75,
        }
        assert current.json() == later.json()


async def test_goal_creation_ack_is_stable_when_replaced_before_delivery(
    committed_client: tuple[AsyncClient, Database, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, user_id = committed_client
    first, replacement = await interleave_commits(
        monkeypatch,
        lambda: client.put("/weight-goals/active", json=GOAL_PAYLOAD),
        lambda: client.put(
            "/weight-goals/active",
            json={**GOAL_PAYLOAD, "target_weight_kg": 90, "baseline_weight_kg": 101},
        ),
    )
    assert first.status_code == replacement.status_code == 200
    first_goal = first.json()
    replacement_goal = replacement.json()
    assert first_goal["id"] != replacement_goal["id"]
    assert first_goal["status"] == "active"
    assert first_goal["ended_at"] is None
    assert first_goal["target_weight_kg"] == 95
    assert first_goal["baseline_weight_kg"] == 100
    assert first_goal["plan"]["total_change_kg"] == -5
    assert replacement_goal["status"] == "active"
    assert replacement_goal["baseline_weight_kg"] == 101
    assert (await client.get("/weight-goals/active")).json() == replacement_goal

    async with database.session_factory() as session:
        goals = list(
            await session.scalars(
                select(WeightGoal).where(WeightGoal.user_id == user_id)
            )
        )
    assert len(goals) == 2
    persisted_first = next(goal for goal in goals if str(goal.id) == first_goal["id"])
    persisted_replacement = next(
        goal for goal in goals if str(goal.id) == replacement_goal["id"]
    )
    assert persisted_first.status == "replaced"
    assert persisted_first.ended_at == persisted_replacement.created_at
    assert sum(goal.status == "active" for goal in goals) == 1


async def test_identical_goal_put_ack_reuses_id_without_extra_history(
    committed_client: tuple[AsyncClient, Database, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, user_id = committed_client
    original = (await client.put("/weight-goals/active", json=GOAL_PAYLOAD)).json()
    same, replacement = await interleave_commits(
        monkeypatch,
        lambda: client.put("/weight-goals/active", json=GOAL_PAYLOAD),
        lambda: client.put(
            "/weight-goals/active", json={**GOAL_PAYLOAD, "target_weight_kg": 90}
        ),
    )
    assert same.status_code == replacement.status_code == 200
    assert same.json() == original
    assert replacement.json()["id"] != original["id"]
    assert (await client.get("/weight-goals/active")).json() == replacement.json()
    async with database.session_factory() as session:
        goals = list(
            await session.scalars(
                select(WeightGoal).where(WeightGoal.user_id == user_id)
            )
        )
    assert len(goals) == 2
    assert sum(goal.status == "active" for goal in goals) == 1


async def test_goal_completion_ack_is_stable_after_new_goal(
    committed_client: tuple[AsyncClient, Database, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database, user_id = committed_client
    original = (await client.put("/weight-goals/active", json=GOAL_PAYLOAD)).json()
    completed, new_goal = await interleave_commits(
        monkeypatch,
        lambda: client.patch(
            f"/weight-goals/{original['id']}", json={"status": "completed"}
        ),
        lambda: client.put(
            "/weight-goals/active", json={**GOAL_PAYLOAD, "target_weight_kg": 90}
        ),
    )
    assert completed.status_code == new_goal.status_code == 200
    assert {
        **completed.json(),
        "status": "active",
        "ended_at": None,
    } == original
    assert completed.json()["status"] == "completed"
    assert completed.json()["ended_at"] is not None
    assert (await client.get("/weight-goals/active")).json() == new_goal.json()
    async with database.session_factory() as session:
        previous = await session.get(WeightGoal, UUID(original["id"]))
    assert previous is not None
    assert previous.status == "completed"
    assert previous.ended_at is not None
    assert previous.user_id == user_id


@pytest.mark.parametrize("action", ["create", "update", "replace_goal"])
async def test_commit_failure_does_not_return_or_persist_snapshot(
    committed_client: tuple[AsyncClient, Database, UUID],
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    client, database, user_id = committed_client
    original = None
    if action == "update":
        original = (
            await client.post(
                "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80.25}
            )
        ).json()
    if action == "replace_goal":
        original = (await client.put("/weight-goals/active", json=GOAL_PAYLOAD)).json()

    async def fail_commit(_: AsyncSession) -> None:
        raise OperationalError("COMMIT", None, RuntimeError("test commit failure"))

    with monkeypatch.context() as patched:
        patched.setattr(AsyncSession, "commit", fail_commit)
        if action == "create":
            response = await client.post(
                "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80.25}
            )
        elif action == "update":
            assert original is not None
            response = await client.patch(
                f"/weight-logs/{original['id']}", json={"weight_kg": 81.25}
            )
        else:
            response = await client.put(
                "/weight-goals/active",
                json={**GOAL_PAYLOAD, "target_weight_kg": 90},
            )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": response.headers["X-Request-ID"],
    }
    if action == "replace_goal":
        assert (await client.get("/weight-goals/active")).json() == original
        async with database.session_factory() as session:
            goals = list(
                await session.scalars(
                    select(WeightGoal).where(WeightGoal.user_id == user_id)
                )
            )
        assert len(goals) == 1
    else:
        assert (await client.get("/weight-logs")).json() == (
            [] if action == "create" else [original]
        )


async def test_known_date_conflicts_rollback_without_changing_committed_logs(
    committed_client: tuple[AsyncClient, Database, UUID],
) -> None:
    client, _, _ = committed_client
    first = (
        await client.post(
            "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80.25}
        )
    ).json()
    second = (
        await client.post(
            "/weight-logs", json={"date": "2026-09-18", "weight_kg": 81.25}
        )
    ).json()
    duplicate = await client.post(
        "/weight-logs", json={"date": "2026-09-17", "weight_kg": 82.25}
    )
    moved = await client.patch(
        f"/weight-logs/{second['id']}",
        json={"date": "2026-09-17", "weight_kg": 82.25},
    )
    for response in (duplicate, moved):
        assert response.status_code == 409
        assert response.json() == {
            "detail": "A weight log already exists for this date"
        }
    assert (await client.get("/weight-logs")).json() == [second, first]


async def test_unrelated_database_constraint_is_not_a_date_conflict(
    committed_client: tuple[AsyncClient, Database, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = committed_client
    original_flush = AsyncSession.flush

    async def fail_check(session: AsyncSession) -> None:
        for log in session.new:
            if isinstance(log, WeightLog):
                log.weight_kg = Decimal("-1")
        await original_flush(session)

    with monkeypatch.context() as patched:
        patched.setattr(AsyncSession, "flush", fail_check)
        response = await client.post(
            "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80.25}
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert (await client.get("/weight-logs")).json() == []
