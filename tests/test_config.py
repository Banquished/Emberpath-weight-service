import pytest

from src.core.config import Settings


def test_defaults_need_no_database(monkeypatch) -> None:
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.app_name == "Emberpath Weight Service"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "development"
    assert settings.database_url is None


def test_database_is_required_when_enabled() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Settings(database_required=True, _env_file=None)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://service:password@localhost:5432/service",
        "postgresql+asyncpg://service:password@localhost:5432/service",
    ],
)
def test_database_url_rejects_unsupported_drivers(database_url: str) -> None:
    with pytest.raises(
        ValueError, match=r"DATABASE_URL must use the postgresql\+psycopg scheme"
    ):
        Settings(database_url=database_url, _env_file=None)


def test_database_url_accepts_psycopg_driver() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://service:password@localhost:5432/service",
        _env_file=None,
    )

    assert (
        str(settings.database_url)
        == "postgresql+psycopg://service:password@localhost:5432/service"
    )


def test_production_requires_explicit_hosts_and_hides_docs() -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS must not contain"):
        Settings(environment="production", _env_file=None)

    settings = Settings(
        environment="production",
        allowed_hosts=["api.example.com"],
        _env_file=None,
    )

    assert settings.effective_docs_enabled is False


def test_production_rejects_empty_allowed_hosts() -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS must not be empty"):
        Settings(environment="production", allowed_hosts=[], _env_file=None)


@pytest.mark.parametrize(
    "host",
    [
        "https://api.example.com",
        "api.example.com:443",
        "api.example.com/path",
        "api example.com",
        "api.*.example.com",
    ],
)
def test_allowed_hosts_rejects_invalid_patterns(host: str) -> None:
    with pytest.raises(ValueError, match="ALLOWED_HOSTS entries"):
        Settings(allowed_hosts=[host], _env_file=None)


def test_allowed_hosts_normalizes_valid_patterns() -> None:
    settings = Settings(
        allowed_hosts=["API.EXAMPLE.COM", "*.INTERNAL.EXAMPLE.COM", "localhost"],
        _env_file=None,
    )

    assert settings.allowed_hosts == [
        "api.example.com",
        "*.internal.example.com",
        "localhost",
    ]


def test_cors_rejects_wildcard_origin_with_credentials() -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS must not contain"):
        Settings(
            cors_origins=["*"],
            cors_allow_credentials=True,
            _env_file=None,
        )


@pytest.mark.parametrize(
    "origin",
    [
        "https://app.example.com/",
        "https://app.example.com/api",
        "https://user@app.example.com",
        "https://*.example.com",
        "https://app.example.com:invalid",
        "https://exa mple.com",
        "https://-bad.example",
        "https://example..com",
        "example.com",
    ],
)
def test_cors_rejects_non_origin_values(origin: str) -> None:
    with pytest.raises(ValueError, match="CORS_ORIGINS entries"):
        Settings(cors_origins=[origin], _env_file=None)


def test_cors_origins_are_canonicalized() -> None:
    settings = Settings(
        cors_origins=[
            "HTTPS://APP.EXAMPLE.COM:443",
            "https://éxample.com",
            "http://LOCALHOST:8080",
            "http://[::1]:80",
        ],
        _env_file=None,
    )

    assert settings.cors_origins == [
        "https://app.example.com",
        "https://xn--xample-9ua.com",
        "http://localhost:8080",
        "http://[::1]",
    ]


def test_cors_methods_are_normalized() -> None:
    settings = Settings(cors_methods=["get", "Post"], _env_file=None)

    assert settings.cors_methods == ["GET", "POST"]


def test_database_pool_settings_are_configurable() -> None:
    settings = Settings(
        database_connect_timeout_seconds=5,
        database_pool_size=12,
        database_max_overflow=4,
        database_pool_timeout_seconds=15,
        database_pool_recycle_seconds=600,
        database_pool_pre_ping=False,
        database_statement_timeout_seconds=5,
        database_lock_timeout_seconds=3,
        database_idle_transaction_timeout_seconds=9,
        _env_file=None,
    )

    assert settings.database_connect_timeout_seconds == 5
    assert settings.database_pool_size == 12
    assert settings.database_max_overflow == 4
    assert settings.database_pool_timeout_seconds == 15
    assert settings.database_pool_recycle_seconds == 600
    assert settings.database_pool_pre_ping is False
    assert settings.database_statement_timeout_seconds == 5
    assert settings.database_lock_timeout_seconds == 3
    assert settings.database_idle_transaction_timeout_seconds == 9


def test_list_settings_accept_comma_separated_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com, api.internal.example.com")
    monkeypatch.setenv(
        "CORS_ORIGINS", "https://app.example.com,https://admin.example.com"
    )
    monkeypatch.setenv("CORS_METHODS", "GET,POST")
    monkeypatch.setenv("CORS_HEADERS", "Authorization,Content-Type")

    settings = Settings(_env_file=None)

    assert settings.allowed_hosts == ["api.example.com", "api.internal.example.com"]
    assert settings.cors_origins == [
        "https://app.example.com",
        "https://admin.example.com",
    ]
    assert settings.cors_methods == ["GET", "POST"]
    assert settings.cors_headers == ["Authorization", "Content-Type"]
    assert settings.cors_allow_credentials is False


def test_environment_overrides_dotenv(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=From file\n"
        "DATABASE_URL=postgresql+psycopg://service:password@localhost:5432/from_file\n"
    )
    monkeypatch.setenv("APP_NAME", "From environment")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(_env_file=env_file)

    assert settings.app_name == "From environment"
    assert (
        str(settings.database_url)
        == "postgresql+psycopg://service:password@localhost:5432/from_file"
    )
