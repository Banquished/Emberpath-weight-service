from fastapi import APIRouter

from src.api.schemas import ServiceMetadata
from src.core.config import Settings


def create_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_model=ServiceMetadata, response_model_exclude_none=True)
    async def metadata() -> ServiceMetadata:
        return ServiceMetadata(
            service=settings.app_name,
            version=settings.app_version,
            documentation="/docs" if settings.effective_docs_enabled else None,
        )

    return router
