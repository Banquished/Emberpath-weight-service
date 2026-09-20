from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command


@pytest.mark.integration
def test_existing_measurements_survive_ownership_migration(test_database_url):
    schema = f"migration_test_{uuid4().hex}"
    engine = create_engine(test_database_url, hide_parameters=True)
    isolated = None
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(test_database_url).update_query_dict(
            {"options": f"-csearch_path={schema}"}
        )
        config = Config("alembic.ini")
        config.attributes["database_url"] = url.render_as_string(hide_password=False)
        command.upgrade(config, "0001")
        isolated = create_engine(url, hide_parameters=True)
        log_id = uuid4()
        with isolated.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO weight_logs (id, date, weight_kg) VALUES (:id, '2026-01-01', 82.35)"
                ),
                {"id": log_id},
            )
        command.upgrade(config, "head")
        command.check(config)
        with isolated.connect() as connection:
            row = connection.execute(
                text("SELECT id, date::text, weight_kg::text, user_id FROM weight_logs")
            ).one()
            assert tuple(row) == (log_id, "2026-01-01", "82.35", None)
    finally:
        if isolated is not None:
            isolated.dispose()
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
