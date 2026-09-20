from sqlalchemy import create_engine, pool

from alembic import context
from src.core.config import get_settings
from src.core.database import Base
from src.models.weight_log import WeightLog  # noqa: F401

target_metadata = Base.metadata
database_url = context.config.attributes.get("database_url")
if database_url is None:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("Set DATABASE_URL before running migrations")
    database_url = str(settings.database_url)

if context.is_offline_mode():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(database_url, poolclass=pool.NullPool, hide_parameters=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
