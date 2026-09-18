from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient


def test_weight_log_lifecycle(client: TestClient) -> None:
    assert client.get("/weight-logs").json() == []
    response = client.post(
        "/weight-logs", json={"date": "2026-09-17", "weight_kg": 82.35}
    )
    assert response.status_code == 201
    log = response.json()
    assert UUID(log["id"])
    assert log == {"id": log["id"], "date": "2026-09-17", "weight_kg": 82.35}
    url = f"/weight-logs/{log['id']}"
    assert client.get(url).status_code == 200
    assert client.get(url).json() == log
    response = client.get("/weight-logs")
    assert response.status_code == 200
    assert response.json() == [log]

    response = client.patch(url, json={"weight_kg": 81.2})
    assert response.status_code == 200
    assert response.json() == {**log, "weight_kg": 81.2}
    response = client.patch(url, json={"date": "2026-09-16"})
    assert response.status_code == 200
    assert response.json() == {**log, "date": "2026-09-16", "weight_kg": 81.2}
    assert client.get(url).json() == response.json()

    response = client.delete(url)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(url).status_code == 404
    assert client.get("/weight-logs").json() == []


def test_logs_are_sorted_by_date_descending(client: TestClient) -> None:
    for day in ["2026-09-16", "2026-09-18", "2026-09-17"]:
        response = client.post("/weight-logs", json={"date": day, "weight_kg": 80})
        assert response.status_code == 201
    assert [log["date"] for log in client.get("/weight-logs").json()] == [
        "2026-09-18",
        "2026-09-17",
        "2026-09-16",
    ]


def test_date_conflicts_do_not_change_existing_logs(client: TestClient) -> None:
    first = client.post(
        "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80}
    ).json()
    second = client.post(
        "/weight-logs", json={"date": "2026-09-18", "weight_kg": 81}
    ).json()
    response = client.post("/weight-logs", json={"date": "2026-09-17", "weight_kg": 82})
    assert response.status_code == 409
    assert isinstance(response.json()["detail"], str)
    response = client.patch(
        f"/weight-logs/{second['id']}",
        json={"date": "2026-09-17", "weight_kg": 79},
    )
    assert response.status_code == 409
    assert client.get("/weight-logs").json() == [second, first]
    assert (
        client.patch(
            f"/weight-logs/{first['id']}", json={"date": "2026-09-17"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_missing_log(client: TestClient, method: str) -> None:
    kwargs = {"json": {"weight_kg": 80}} if method == "patch" else {}
    response = client.request(method, f"/weight-logs/{uuid4()}", **kwargs)
    assert response.status_code == 404
    assert response.json() == {"detail": "Weight log not found"}


@pytest.mark.parametrize(
    "payload",
    [
        {"date": "not-a-date", "weight_kg": 80},
        {"date": "2026-02-30", "weight_kg": 80},
        {"date": "2026-09-17", "weight_kg": 0},
        {"date": "2026-09-17", "weight_kg": -1},
        {"date": "2026-09-17", "weight_kg": 80.123},
        {"date": "2026-09-17", "weight_kg": 10000},
        {"date": "2026-09-17", "weight_kg": "NaN"},
        {"date": "2026-09-17", "weight_kg": None},
        {"date": None, "weight_kg": 80},
        {"date": "2026-09-17"},
        {"weight_kg": 80},
        {"date": "2026-09-17", "weight_kg": 80, "note": "unsupported"},
    ],
)
def test_invalid_create(client: TestClient, payload: dict) -> None:
    assert client.post("/weight-logs", json=payload).status_code == 422
    assert client.get("/weight-logs").json() == []


@pytest.mark.parametrize(
    "payload",
    [{}, {"date": None}, {"weight_kg": None}, {"weight_kg": 0}, {"weight_kg": 80.123}],
)
def test_invalid_update_keeps_log_unchanged(client: TestClient, payload: dict) -> None:
    log = client.post(
        "/weight-logs", json={"date": "2026-09-17", "weight_kg": 80}
    ).json()
    url = f"/weight-logs/{log['id']}"
    assert client.patch(url, json=payload).status_code == 422
    assert client.get(url).json() == log


def test_invalid_id(client: TestClient) -> None:
    assert client.get("/weight-logs/not-a-uuid").status_code == 422
