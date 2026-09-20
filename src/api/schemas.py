from pydantic import BaseModel, Field


class StatusResponse(BaseModel):
    status: str = Field(description="Operational status")


class ErrorResponse(BaseModel):
    detail: str = Field(description="Human-readable error summary")
    request_id: str = Field(
        description="Identifier for correlating the request in logs"
    )


class ServiceMetadata(BaseModel):
    service: str = Field(description="Service name")
    version: str = Field(description="Service version")
    documentation: str | None = Field(
        default=None, description="Interactive API documentation path, when enabled"
    )
