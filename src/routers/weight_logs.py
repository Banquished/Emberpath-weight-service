from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import CurrentUser
from src.core.database import get_session
from src.models.weight_log import WeightLog
from src.schemas.weight_log import WeightLogCreate, WeightLogRead, WeightLogUpdate

router = APIRouter(prefix="/weight-logs", tags=["weight logs"])
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


async def find_log(log_id: UUID, user_id: UUID, session: AsyncSession) -> WeightLog:
    log = await session.scalar(
        select(WeightLog).where(WeightLog.id == log_id, WeightLog.user_id == user_id)
    )
    if log is None:
        raise HTTPException(status_code=404, detail="Weight log not found")
    return log


async def save_log(log: WeightLog, session: AsyncSession) -> WeightLog:
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        if (
            isinstance(error.orig, UniqueViolation)
            and error.orig.diag.constraint_name == "uq_weight_logs_user_date"
        ):
            raise HTTPException(
                status_code=409, detail="A weight log already exists for this date"
            ) from error
        raise
    await session.refresh(log)
    return log


@router.post("", response_model=WeightLogRead, status_code=status.HTTP_201_CREATED)
async def create_weight_log(
    payload: WeightLogCreate, user_id: CurrentUser, session: DatabaseSession
) -> WeightLog:
    log = WeightLog(**payload.model_dump(), user_id=user_id)
    session.add(log)
    return await save_log(log, session)


@router.get("", response_model=list[WeightLogRead])
async def list_weight_logs(
    user_id: CurrentUser, session: DatabaseSession
) -> list[WeightLog]:
    return list(
        await session.scalars(
            select(WeightLog)
            .where(WeightLog.user_id == user_id)
            .order_by(WeightLog.date.desc())
        )
    )


@router.get("/{log_id}", response_model=WeightLogRead)
async def get_weight_log(
    log_id: UUID, user_id: CurrentUser, session: DatabaseSession
) -> WeightLog:
    return await find_log(log_id, user_id, session)


@router.patch("/{log_id}", response_model=WeightLogRead)
async def update_weight_log(
    log_id: UUID,
    payload: WeightLogUpdate,
    user_id: CurrentUser,
    session: DatabaseSession,
) -> WeightLog:
    log = await find_log(log_id, user_id, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(log, field, value)
    return await save_log(log, session)


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_weight_log(
    log_id: UUID, user_id: CurrentUser, session: DatabaseSession
) -> Response:
    await session.delete(await find_log(log_id, user_id, session))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
