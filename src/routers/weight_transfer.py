import csv
import io
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import CurrentUser
from src.core.database import get_session
from src.domain.weight_transfer import parse_import, preview_import
from src.models.weight_log import WeightLog
from src.schemas.weight_transfer import (
    ImportCommit,
    ImportPreview,
    ImportRequest,
    ImportResult,
    TransferDelimiter,
)

router = APIRouter(prefix="/weight-logs", tags=["weight logs"])
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


@router.get("/export")
async def export_weight_logs(
    user_id: CurrentUser,
    session: DatabaseSession,
    delimiter: TransferDelimiter = "comma",
) -> Response:
    logs = await session.scalars(
        select(WeightLog).where(WeightLog.user_id == user_id).order_by(WeightLog.date)
    )
    output = io.StringIO(newline="")
    writer = csv.writer(
        output, delimiter={"comma": ",", "semicolon": ";", "tab": "\t"}[delimiter]
    )
    writer.writerow(["date", "weight", "unit"])
    for log in logs:
        writer.writerow([log.date.isoformat(), f"{log.weight_kg:.2f}", "kg"])
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="emberpath-weight-logs.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/import/preview", response_model=ImportPreview)
async def preview_weight_import(
    payload: ImportRequest, user_id: CurrentUser, session: DatabaseSession
) -> ImportPreview:
    rows = parse_import(payload)
    dates = [row.date for row in rows if row.date is not None]
    existing = list(
        await session.scalars(
            select(WeightLog).where(
                WeightLog.user_id == user_id, WeightLog.date.in_(dates)
            )
        )
    )
    return preview_import(payload, rows, existing, user_id)


@router.post("/import", response_model=ImportResult)
async def import_weight_logs(
    payload: ImportCommit, user_id: CurrentUser, session: DatabaseSession
) -> ImportResult:
    rows = parse_import(payload)
    dates = [row.date for row in rows if row.date is not None]
    existing = list(
        await session.scalars(
            select(WeightLog)
            .where(WeightLog.user_id == user_id, WeightLog.date.in_(dates))
            .order_by(WeightLog.date)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    preview = preview_import(payload, rows, existing, user_id)
    if preview.errors:
        raise HTTPException(422, "Correct all invalid rows before importing")
    if preview.preview_token != payload.preview_token:
        raise HTTPException(409, "Measurements changed; preview the file again")
    by_date = {log.date: log for log in existing}
    for row in rows:
        if row.action == "skip":
            continue
        assert row.date is not None and row.weight_kg is not None
        weight = Decimal(str(row.weight_kg))
        if row.action == "replace":
            by_date[row.date].weight_kg = weight
        else:
            session.add(WeightLog(user_id=user_id, date=row.date, weight_kg=weight))
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            409, "Measurements changed; preview the file again"
        ) from error
    return ImportResult(
        imported=preview.imported, replaced=preview.replaced, skipped=preview.skipped
    )
