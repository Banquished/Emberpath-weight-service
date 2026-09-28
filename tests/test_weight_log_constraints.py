from unittest.mock import Mock

import pytest
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError, OperationalError

from src.models.weight_log import is_weight_log_date_conflict


@pytest.mark.parametrize(
    "constraint_name,expected",
    [
        ("uq_weight_logs_user_date", True),
        ("ck_weight_logs_positive_weight", False),
        (None, False),
    ],
)
def test_weight_log_date_conflict_matches_only_named_unique_constraint(
    constraint_name: str | None, expected: bool
) -> None:
    violation = Mock(spec=UniqueViolation)
    violation.diag.constraint_name = constraint_name
    error = IntegrityError("INSERT", None, violation)

    assert is_weight_log_date_conflict(error) is expected


def test_weight_log_date_conflict_requires_psycopg_integrity_error() -> None:
    violation = Mock(spec=UniqueViolation)
    violation.diag.constraint_name = "uq_weight_logs_user_date"

    assert not is_weight_log_date_conflict(OperationalError("INSERT", None, violation))
    assert not is_weight_log_date_conflict(
        IntegrityError("INSERT", None, ValueError("duplicate"))
    )
