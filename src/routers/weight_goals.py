from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.auth import CurrentUser
from src.core.database import get_session
from src.models.user import User
from src.models.weight_goal import WeightGoal
from src.models.weight_log import WeightLog
from src.schemas.weight_goal import WeightGoalEnd, WeightGoalRead, WeightGoalSet

router = APIRouter(prefix="/weight-goals", tags=["weight goals"])
DatabaseSession = Annotated[AsyncSession, Depends(get_session)]


async def active_goal(user_id: UUID, session: AsyncSession) -> WeightGoal | None:
    return await session.scalar(
        select(WeightGoal).where(
            WeightGoal.user_id == user_id, WeightGoal.status == "active"
        )
    )


@router.get("/active", response_model=WeightGoalRead | None)
async def get_active_goal(
    user_id: CurrentUser, session: DatabaseSession
) -> WeightGoal | None:
    return await active_goal(user_id, session)


@router.put("/active", response_model=WeightGoalRead)
async def set_active_goal(
    payload: WeightGoalSet, user_id: CurrentUser, session: DatabaseSession
) -> WeightGoal:
    # Lock the owner even when no goal exists, serializing concurrent replacements.
    await session.scalar(select(User).where(User.id == user_id).with_for_update())
    previous = await active_goal(user_id, session)
    values = payload.model_dump()
    baseline = payload.baseline_weight_kg
    if baseline is None:
        if previous is not None and previous.start_date == payload.start_date:
            baseline = previous.baseline_weight_kg
        if baseline is None:
            baseline = await session.scalar(
                select(WeightLog.weight_kg)
                .where(
                    WeightLog.user_id == user_id, WeightLog.date <= payload.start_date
                )
                .order_by(WeightLog.date.desc())
                .limit(1)
            )
    if payload.target_date is not None and baseline is None:
        raise HTTPException(
            status_code=422,
            detail="Enter a starting weight or record a measurement on or before the goal start date.",
        )
    values["baseline_weight_kg"] = baseline
    if previous is not None and all(
        getattr(previous, field) == value for field, value in values.items()
    ):
        await session.commit()
        return previous
    now = datetime.now(UTC)
    if previous is not None:
        previous.status = "replaced"
        previous.ended_at = now
        await session.flush()
    goal = WeightGoal(**values, user_id=user_id, status="active", created_at=now)
    session.add(goal)
    await session.commit()
    await session.refresh(goal)
    return goal


@router.patch("/{goal_id}", response_model=WeightGoalRead)
async def end_goal(
    goal_id: UUID,
    payload: WeightGoalEnd,
    user_id: CurrentUser,
    session: DatabaseSession,
) -> WeightGoal:
    await session.scalar(select(User).where(User.id == user_id).with_for_update())
    goal = await session.scalar(
        select(WeightGoal).where(
            WeightGoal.id == goal_id, WeightGoal.user_id == user_id
        )
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="Weight goal not found")
    if goal.status != "active":
        raise HTTPException(status_code=409, detail="Weight goal is no longer active")
    goal.status = payload.status
    goal.ended_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(goal)
    return goal
