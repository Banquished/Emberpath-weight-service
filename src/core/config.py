import re
from functools import lru_cache
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

HOST_LABEL_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def normalize_origin_hostname(hostname: str) -> str:
    try:
        address = ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        return address.compressed
    try:
        normalized_hostname = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError from error
    if any(
        not HOST_LABEL_PATTERN.fullmatch(label)
        for label in normalized_hostname.split(".")
    ):
        raise ValueError
    return normalized_hostname


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    app_name: str = "Emberpath Weight Service"
    clerk_issuer: str | None = None
    clerk_authorized_parties: Annotated[list[str], NoDecode] = []
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "production"] = "development"
    database_url: PostgresDsn | None = None
    database_required: bool = False
    database_connect_timeout_seconds: int = Field(default=10, ge=1, le=60)
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    database_pool_recycle_seconds: int = Field(default=1800, ge=1, le=86400)
    database_pool_pre_ping: bool = True
    database_statement_timeout_seconds: int = Field(default=30, ge=1, le=3600)
    database_lock_timeout_seconds: int = Field(default=10, ge=1, le=3600)
    database_idle_transaction_timeout_seconds: int = Field(default=60, ge=1, le=3600)
    allowed_hosts: Annotated[list[str], NoDecode] = ["*"]
    cors_origins: Annotated[list[str], NoDecode] = []
    cors_methods: Annotated[list[str], NoDecode] = ["GET"]
    cors_headers: Annotated[list[str], NoDecode] = ["Content-Type", "X-Request-ID"]
    cors_allow_credentials: bool = False
    docs_enabled: bool | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("clerk_issuer")
    @classmethod
    def validate_clerk_issuer(cls, value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CLERK_ISSUER must be an HTTPS origin")
        return value.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def validate_database_driver(cls, value: PostgresDsn | None) -> PostgresDsn | None:
        if value is not None and value.scheme != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use the postgresql+psycopg scheme")
        return value

    # Pydantic Settings otherwise expects a JSON array for list-valued environment variables.
    @field_validator(
        "allowed_hosts",
        "cors_origins",
        "cors_methods",
        "cors_headers",
        "clerk_authorized_parties",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, values: list[str]) -> list[str]:
        normalized_hosts: list[str] = []
        for value in values:
            host = value.lower()
            if host == "*":
                normalized_hosts.append(host)
                continue
            hostname = host.removeprefix("*.")
            if (
                "*" in hostname
                or not hostname
                or any(
                    not HOST_LABEL_PATTERN.fullmatch(label)
                    for label in hostname.split(".")
                )
            ):
                raise ValueError(
                    "ALLOWED_HOSTS entries must be hostnames with an optional '*.' prefix"
                )
            normalized_hosts.append(host)
        return normalized_hosts

    @field_validator("cors_origins", "clerk_authorized_parties")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        normalized_origins: list[str] = []
        for origin in values:
            if origin == "*":
                normalized_origins.append(origin)
                continue
            parsed = urlsplit(origin)
            try:
                port = parsed.port
            except ValueError as error:
                raise ValueError(
                    "CORS_ORIGINS entries must be valid http(s) origins"
                ) from error
            hostname = parsed.hostname
            if (
                parsed.scheme not in {"http", "https"}
                or hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or "*" in hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS_ORIGINS entries must be valid http(s) origins")
            try:
                normalized_host = normalize_origin_hostname(hostname)
            except ValueError as error:
                raise ValueError(
                    "CORS_ORIGINS entries must be valid http(s) origins"
                ) from error
            if ":" in normalized_host:
                normalized_host = f"[{normalized_host}]"
            default_port = 80 if parsed.scheme == "http" else 443
            port_suffix = (
                f":{port}" if port is not None and port != default_port else ""
            )
            normalized_origins.append(
                f"{parsed.scheme}://{normalized_host}{port_suffix}"
            )
        return normalized_origins

    @field_validator("clerk_authorized_parties")
    @classmethod
    def reject_wildcard_parties(cls, values: list[str]) -> list[str]:
        if "*" in values:
            raise ValueError("CLERK_AUTHORIZED_PARTIES must contain explicit origins")
        return values

    @field_validator("cors_methods")
    @classmethod
    def normalize_cors_methods(cls, values: list[str]) -> list[str]:
        return [method.upper() for method in values]

    @model_validator(mode="after")
    def validate_required_database(self) -> "Settings":
        if self.database_required and self.database_url is None:
            raise ValueError("DATABASE_URL is required when DATABASE_REQUIRED is true")
        if self.environment == "production" and "*" in self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must not contain '*' in production")
        if self.environment == "production" and not self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must not be empty in production")
        if self.cors_allow_credentials and "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS must not contain '*' when credentials are enabled"
            )
        return self

    @property
    def effective_docs_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
