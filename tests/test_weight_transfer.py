from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.weight_log import WeightLog
from src.schemas.weight_transfer import TransferDelimiter

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "delimiter_name,separator", [("comma", ","), ("semicolon", ";"), ("tab", "\t")]
)
async def test_transfer_roundtrip(
    client: AsyncClient, delimiter_name: str, separator: str
) -> None:
    content = "\ufeff" + separator.join(["unit", "date", "weight"]) + "\r\n"
    content += separator.join(['"lb"', '"2026-09-21"', '"220"']) + "\r\n\r\n"
    content += separator.join(["KG", "2026-09-20", "100.01"])
    payload = {"content": content, "delimiter": delimiter_name}
    response = await client.post("/weight-logs/import/preview", json=payload)
    assert response.status_code == 200
    preview = response.json()
    assert preview["imported"] == 2 and preview["errors"] == 0
    assert preview["rows"][0]["weight_kg"] == 99.79
    assert (await client.get("/weight-logs")).json() == []
    response = await client.post(
        "/weight-logs/import",
        json={**payload, "preview_token": preview["preview_token"]},
    )
    assert response.json() == {"imported": 2, "replaced": 0, "skipped": 0}
    exported = await client.get(
        "/weight-logs/export", params={"delimiter": delimiter_name}
    )
    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "no-store"
    assert "weight-logs.csv" in exported.headers["content-disposition"]
    assert (
        exported.text
        == separator.join(["date", "weight", "unit"])
        + "\r\n"
        + separator.join(["2026-09-20", "100.01", "kg"])
        + "\r\n"
        + separator.join(["2026-09-21", "99.79", "kg"])
        + "\r\n"
    )
    roundtrip = await client.post(
        "/weight-logs/import/preview",
        json={"content": exported.text, "delimiter": delimiter_name},
    )
    assert roundtrip.json()["skipped"] == 2


@pytest.mark.parametrize(
    "record",
    [
        "2026-02-30,80,kg",
        "20260921,80,kg",
        "2026-09-21,0,kg",
        "2026-09-21,-80,kg",
        "2026-09-21,NaN,kg",
        "2026-09-21,1e2,kg",
        "2026-09-21,=80,kg",
        "2026-09-21,80.001,kg",
        "2026-09-21,80,stone",
        "2026-09-21,10000,kg",
        "2026-09-21,0.000001,lb",
        "2026-09-21,80,kg,extra",
    ],
)
async def test_invalid_import_is_atomic(client: AsyncClient, record: str) -> None:
    payload = {
        "content": "date,weight,unit\n2026-09-19,90,kg\n" + record,
        "delimiter": "comma",
    }
    preview = (await client.post("/weight-logs/import/preview", json=payload)).json()
    assert preview["errors"] == 1
    assert preview["rows"][1]["action"] == "error"
    response = await client.post(
        "/weight-logs/import",
        json={**payload, "preview_token": preview["preview_token"]},
    )
    assert response.status_code == 422
    assert (await client.get("/weight-logs")).json() == []


@pytest.mark.parametrize(
    "content",
    [
        "",
        "date,weight\n2026-09-21,80",
        "date,date,unit\n2026-09-21,80,kg",
        'date,weight,unit\n"unterminated',
        "date,weight,unit\n",
    ],
)
async def test_bad_file(client: AsyncClient, content: str) -> None:
    response = await client.post(
        "/weight-logs/import/preview", json={"content": content, "delimiter": "comma"}
    )
    assert response.status_code == 422


async def test_duplicate_file_dates(client: AsyncClient) -> None:
    preview = (
        await client.post(
            "/weight-logs/import/preview",
            json={
                "content": "date,weight,unit\n2026-09-21,80,kg\n2026-09-21,81,kg",
                "delimiter": "comma",
            },
        )
    ).json()
    assert preview["errors"] == 2
    assert all(row["action"] == "error" for row in preview["rows"])


@pytest.mark.parametrize("policy", ["skip", "replace"])
async def test_existing_and_ownership(client: AsyncClient, policy: str) -> None:
    original = (
        await client.post("/weight-logs", json={"date": "2026-09-21", "weight_kg": 80})
    ).json()
    other_headers = {"X-Test-Subject": "other_import_user"}
    other = (
        await client.post(
            "/weight-logs",
            headers=other_headers,
            json={"date": "2026-09-21", "weight_kg": 70},
        )
    ).json()
    payload = {
        "content": "date,weight,unit\n2026-09-21,90,kg\n2026-09-22,91,kg",
        "delimiter": "comma",
        "duplicate_policy": policy,
    }
    preview = (await client.post("/weight-logs/import/preview", json=payload)).json()
    assert preview["rows"][0]["action"] == policy
    result = await client.post(
        "/weight-logs/import",
        json={**payload, "preview_token": preview["preview_token"]},
    )
    assert result.status_code == 200
    assert result.json() == {
        "imported": 1,
        "replaced": int(policy == "replace"),
        "skipped": int(policy == "skip"),
    }
    logs = (await client.get("/weight-logs")).json()
    assert logs[1]["id"] == original["id"]
    assert logs[1]["weight_kg"] == (90 if policy == "replace" else 80)
    assert (await client.get("/weight-logs", headers=other_headers)).json() == [other]
    exported = await client.get("/weight-logs/export", headers=other_headers)
    assert exported.text == "date,weight,unit\r\n2026-09-21,70.00,kg\r\n"


@pytest.mark.parametrize(
    "change", ["update", "insert", "delete", "input", "policy", "user"]
)
async def test_stale_preview(client: AsyncClient, change: str) -> None:
    original = (
        await client.post("/weight-logs", json={"date": "2026-09-21", "weight_kg": 80})
    ).json()
    payload = {
        "content": "date,weight,unit\n2026-09-21,90,kg\n2026-09-22,91,kg",
        "delimiter": "comma",
    }
    preview = (await client.post("/weight-logs/import/preview", json=payload)).json()
    headers = {}
    if change == "update":
        await client.patch(f"/weight-logs/{original['id']}", json={"weight_kg": 82})
    elif change == "insert":
        await client.post("/weight-logs", json={"date": "2026-09-22", "weight_kg": 82})
    elif change == "delete":
        await client.delete(f"/weight-logs/{original['id']}")
    elif change == "input":
        payload["content"] = payload["content"].replace("91", "92")
    elif change == "policy":
        payload["duplicate_policy"] = "replace"
    else:
        headers = {"X-Test-Subject": "another_user"}
    before = (await client.get("/weight-logs", headers=headers)).json()
    response = await client.post(
        "/weight-logs/import",
        headers=headers,
        json={**payload, "preview_token": preview["preview_token"]},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Measurements changed; preview the file again"}
    assert (await client.get("/weight-logs", headers=headers)).json() == before


@pytest.mark.integration
@pytest.mark.parametrize(
    "failure,expected_status,expected_detail",
    [
        ("duplicate", 409, "Measurements changed; preview the file again"),
        ("check", 500, "Internal server error"),
        ("database", 500, "Internal server error"),
    ],
)
async def test_import_commit_database_failure_is_atomic(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: str,
    expected_status: int,
    expected_detail: str,
) -> None:
    original = (
        await client.post("/weight-logs", json={"date": "2026-09-21", "weight_kg": 80})
    ).json()
    payload = {
        "content": (
            "date,weight,unit\n2026-09-21,90,kg\n2026-09-22,91,kg\n2026-09-23,92,kg"
        ),
        "delimiter": "comma",
        "duplicate_policy": "replace",
    }
    preview_response = await client.post("/weight-logs/import/preview", json=payload)
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["imported"] == 2 and preview["replaced"] == 1
    commit = AsyncSession.commit

    async def commit_with_failure(session: AsyncSession) -> None:
        pending = [log for log in session.new if isinstance(log, WeightLog)]
        if pending:
            if failure == "database":
                await session.flush()
                raise OperationalError("COMMIT", None, RuntimeError("database failure"))
            owner_id = pending[0].user_id
            assert owner_id is not None
            session.add(
                WeightLog(
                    user_id=owner_id,
                    date=date(2026, 9, 22 if failure == "duplicate" else 24),
                    weight_kg=Decimal("93" if failure == "duplicate" else "-1"),
                )
            )
        await commit(session)

    with monkeypatch.context() as patched:
        patched.setattr(AsyncSession, "commit", commit_with_failure)
        response = await client.post(
            "/weight-logs/import",
            json={**payload, "preview_token": preview["preview_token"]},
        )

    assert response.status_code == expected_status
    if failure == "duplicate":
        assert response.json() == {"detail": expected_detail}
    else:
        assert response.json() == {
            "detail": expected_detail,
            "request_id": response.headers["X-Request-ID"],
        }
        assert any(record.message == "unhandled_exception" for record in caplog.records)
    assert (await client.get("/weight-logs")).json() == [original]


async def test_import_requires_preview_and_limits(client: AsyncClient) -> None:
    payload = {"content": "date,weight,unit\n2026-09-21,80,kg", "delimiter": "comma"}
    assert (await client.post("/weight-logs/import", json=payload)).status_code == 422
    for content in [
        "x" * 1_048_577,
        "date,weight,unit\n" + "2026-09-21,80,kg\n" * 10_001,
        "\u00e9" * 524_289,
    ]:
        assert (
            await client.post(
                "/weight-logs/import/preview", json={**payload, "content": content}
            )
        ).status_code == 422
    assert (await client.get("/weight-logs/export?delimiter=xlsx")).status_code == 422


def test_invalid_unicode_is_rejected() -> None:
    from fastapi import HTTPException

    from src.domain.weight_transfer import parse_import
    from src.schemas.weight_transfer import ImportRequest

    with pytest.raises(HTTPException) as error:
        parse_import(
            ImportRequest.model_construct(
                content="date,weight,unit\n\ud800", delimiter="comma"
            )
        )
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    "delimiter_name,separator",
    [("comma", ","), ("semicolon", ";"), ("tab", "\t")],
)
def test_parse_import_delimiters_without_database(
    delimiter_name: TransferDelimiter, separator: str
) -> None:
    from src.domain.weight_transfer import parse_import
    from src.schemas.weight_transfer import ImportRequest

    content = separator.join(["date", "weight", "unit"])
    content += "\n" + separator.join(["2026-09-21", "220", "lb"])
    rows = parse_import(ImportRequest(content=content, delimiter=delimiter_name))
    assert len(rows) == 1
    assert rows[0].weight_kg == 99.79
    assert rows[0].errors == []
