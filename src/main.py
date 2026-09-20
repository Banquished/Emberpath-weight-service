import logging
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from src.api.schemas import ErrorResponse
from src.core.config import Settings, get_settings
from src.core.database import Database
from src.core.logging import configure_logging
from src.core.middleware import (
    PlainTextErrorResponseMiddleware,
    RequestContextMiddleware,
    UnhandledErrorMiddleware,
)
from src.routers.health import create_router as create_health_router
from src.routers.metadata import create_router as create_metadata_router
from src.routers.weight_logs import router as weight_router

logger = logging.getLogger(__name__)


def create_lifespan(database: Database):
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        await database.dispose()

    return lifespan


def error_response(
    request: Request,
    status_code: int,
    detail: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    response = JSONResponse(
        status_code=status_code,
        headers=headers,
        content=ErrorResponse(
            detail=detail,
            request_id=request_id,
        ).model_dump(),
    )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def is_weight_path(path: str) -> bool:
    return path == "/weight-logs" or path.startswith("/weight-logs/")


async def validation_error_handler(request: Request, error: Exception) -> JSONResponse:
    if is_weight_path(request.url.path):
        return await request_validation_exception_handler(
            request, cast(RequestValidationError, error)
        )
    return error_response(
        request, status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid request"
    )


async def http_error_handler(request: Request, error: Exception) -> Response:
    http_error = cast(StarletteHTTPException, error)
    if is_weight_path(request.url.path):
        return await http_exception_handler(request, http_error)
    return error_response(
        request, http_error.status_code, str(http_error.detail), http_error.headers
    )


async def unhandled_error_handler(request: Request, _: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={"request_id": getattr(request.state, "request_id", "unknown")},
    )
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Internal server error",
    )


def configure_openapi(application: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema

        openapi_schema = get_openapi(
            title=application.title,
            version=application.version,
            routes=application.routes,
        )
        error_response_schema = ErrorResponse.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        components = openapi_schema.setdefault("components", {}).setdefault(
            "schemas", {}
        )
        components["ErrorResponse"] = error_response_schema

        paths = cast(dict[str, object], openapi_schema["paths"])
        for path, path_item_value in paths.items():
            if is_weight_path(path):
                continue
            if not isinstance(path_item_value, dict):
                continue
            path_item = cast(dict[str, object], path_item_value)
            for operation_value in path_item.values():
                if not isinstance(operation_value, dict):
                    continue
                operation = cast(dict[str, object], operation_value)
                responses = operation.get("responses")
                if not isinstance(responses, dict):
                    continue
                responses = cast(dict[str, object], responses)
                validation_response = responses.get("422")
                if isinstance(validation_response, dict):
                    cast(dict[str, object], validation_response)["content"] = {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                        }
                    }

        application.openapi_schema = openapi_schema
        return application.openapi_schema

    application.openapi = openapi


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    database = Database(app_settings)
    configure_logging(app_settings.log_level)
    application = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=create_lifespan(database),
        docs_url="/docs" if app_settings.effective_docs_enabled else None,
        redoc_url="/redoc" if app_settings.effective_docs_enabled else None,
        openapi_url="/openapi.json" if app_settings.effective_docs_enabled else None,
    )
    application.add_middleware(
        UnhandledErrorMiddleware, handler=unhandled_error_handler
    )
    if app_settings.cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_credentials=app_settings.cors_allow_credentials,
            allow_methods=app_settings.cors_methods,
            allow_headers=app_settings.cors_headers,
            expose_headers=["X-Request-ID"],
        )
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=app_settings.allowed_hosts
    )
    application.add_middleware(PlainTextErrorResponseMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_error_handler)
    application.state.database = database
    application.include_router(create_metadata_router(app_settings))
    application.include_router(create_health_router(app_settings, database))
    application.include_router(weight_router)
    configure_openapi(application)
    return application


app = create_app()
