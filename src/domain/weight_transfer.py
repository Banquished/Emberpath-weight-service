import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from src.models.weight_log import WeightLog
from src.schemas.weight_log import WeightKg
from src.schemas.weight_transfer import ImportPreview, ImportRequest, ImportRow

weight_adapter = TypeAdapter[Decimal](WeightKg)


def parse_import(payload: ImportRequest) -> list[ImportRow]:
    try:
        encoded = payload.content.encode("utf-8")
    except UnicodeError as error:
        raise HTTPException(422, "File must contain valid UTF-8 text") from error
    if len(encoded) > 1_048_576:
        raise HTTPException(422, "File must not exceed 1 MiB")
    reader = csv.reader(
        io.StringIO(payload.content.lstrip("\ufeff"), newline=""),
        delimiter={"comma": ",", "semicolon": ";", "tab": "\t"}[payload.delimiter],
        strict=True,
    )
    rows: list[ImportRow] = []
    try:
        header = [value.strip().lower() for value in next(reader, list[str]())]
        if len(header) != 3 or set(header) != {"date", "weight", "unit"}:
            raise HTTPException(422, "Headers must be date,weight,unit")
        for values in reader:
            if not values or all(not value.strip() for value in values):
                continue
            if len(rows) >= 10_000:
                raise HTTPException(422, "File must not exceed 10000 measurements")
            row = ImportRow(row=reader.line_num)
            rows.append(row)
            if len(values) != 3:
                row.errors.append("Expected exactly three columns")
                continue
            fields = dict(zip(header, (value.strip() for value in values), strict=True))
            try:
                if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", fields["date"]):
                    raise ValueError
                row.date = date.fromisoformat(fields["date"])
            except ValueError:
                row.errors.append("Date must be a valid YYYY-MM-DD date")
            unit = fields["unit"].lower()
            if unit not in {"kg", "lb"}:
                row.errors.append("Unit must be kg or lb")
            try:
                if not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,6})?", fields["weight"]):
                    raise ValueError
                weight = Decimal(fields["weight"])
                if unit == "lb":
                    weight = (weight * Decimal("0.45359237")).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    )
                row.weight_kg = float(weight_adapter.validate_python(weight))
            except (ValueError, ValidationError):
                row.errors.append(
                    "Weight must be positive and fit 0.01-9999.99 kg; kg allows two decimals, lb six"
                )
    except csv.Error as error:
        raise HTTPException(422, "Malformed delimited file") from error
    if not rows:
        raise HTTPException(422, "File must contain at least one measurement")
    counts = Counter(row.date for row in rows if row.date is not None)
    for row in rows:
        if row.date is not None and counts[row.date] > 1:
            row.errors.append("Date appears more than once in this file")
        if row.errors:
            row.action = "error"
    return rows


def preview_import(
    payload: ImportRequest,
    rows: list[ImportRow],
    existing: list[WeightLog],
    user_id: UUID,
) -> ImportPreview:
    by_date = {log.date: log for log in existing}
    for row in rows:
        if not row.errors and row.date in by_date:
            row.action = "replace" if payload.duplicate_policy == "replace" else "skip"
    state = [
        (str(log.id), log.date.isoformat(), str(log.weight_kg)) for log in existing
    ]
    digest = hashlib.sha256(
        json.dumps(
            [
                str(user_id),
                payload.content,
                payload.delimiter,
                payload.duplicate_policy,
                sorted(state),
            ]
        ).encode("utf-8")
    ).hexdigest()
    return ImportPreview(
        rows=rows,
        imported=sum(row.action == "import" for row in rows),
        replaced=sum(row.action == "replace" for row in rows),
        skipped=sum(row.action == "skip" for row in rows),
        errors=sum(row.action == "error" for row in rows),
        preview_token=digest,
    )
