from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.api.schemas import ErrorResponse, StatusResponse
from src.core.config import Settings
from src.core.database import Database


def create_router(settings: Settings, database: Database) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=StatusResponse)
    async def healthz() -> StatusResponse:
        return StatusResponse(status="ok")

    @router.get(
        "/readyz",
        response_model=StatusResponse,
        status_code=status.HTTP_200_OK,
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": ErrorResponse,
                "description": "Database is unavailable",
            }
        },
    )
    async def readyz() -> StatusResponse:
        if not settings.database_required:
            return StatusResponse(status="ok")

        try:
            async with database.session_factory() as session:
                await session.execute(text("SELECT 1"))
        except SQLAlchemyError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database is unavailable",
            ) from error

        return StatusResponse(status="ok")

    return router
