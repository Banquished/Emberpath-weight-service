from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.database import get_session
from src.models.weight_log import WeightLog
from src.schemas.weight_log import WeightLogCreate, WeightLogRead, WeightLogUpdate

router = APIRouter(prefix="/weight-logs", tags=["weight logs"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def find_log(log_id: UUID, session: Session) -> WeightLog:
    log = session.get(WeightLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Weight log not found")
    return log


def save_log(log: WeightLog, session: Session) -> WeightLog:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if (
            isinstance(error.orig, UniqueViolation)
            and error.orig.diag.constraint_name == "uq_weight_logs_date"
        ):
            raise HTTPException(
                status_code=409, detail="A weight log already exists for this date"
            ) from error
        raise
    session.refresh(log)
    return log


@router.post("", response_model=WeightLogRead, status_code=status.HTTP_201_CREATED)
def create_weight_log(payload: WeightLogCreate, session: DatabaseSession) -> WeightLog:
    log = WeightLog(**payload.model_dump())
    session.add(log)
    return save_log(log, session)


@router.get("", response_model=list[WeightLogRead])
def list_weight_logs(session: DatabaseSession) -> list[WeightLog]:
    return list(session.scalars(select(WeightLog).order_by(WeightLog.date.desc())))


@router.get("/{log_id}", response_model=WeightLogRead)
def get_weight_log(log_id: UUID, session: DatabaseSession) -> WeightLog:
    return find_log(log_id, session)


@router.patch("/{log_id}", response_model=WeightLogRead)
def update_weight_log(
    log_id: UUID, payload: WeightLogUpdate, session: DatabaseSession
) -> WeightLog:
    log = find_log(log_id, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(log, field, value)
    return save_log(log, session)


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_weight_log(log_id: UUID, session: DatabaseSession) -> Response:
    session.delete(find_log(log_id, session))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
