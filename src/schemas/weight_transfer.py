from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TransferDelimiter = Literal["comma", "semicolon", "tab"]
DuplicatePolicy = Literal["skip", "replace"]


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=1_048_576)
    delimiter: TransferDelimiter
    duplicate_policy: DuplicatePolicy = "skip"


class ImportCommit(ImportRequest):
    preview_token: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImportRow(BaseModel):
    row: int
    date: Date | None = None
    weight_kg: float | None = None
    action: Literal["import", "replace", "skip", "error"] = "import"
    errors: list[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    imported: int
    replaced: int
    skipped: int


class ImportPreview(ImportResult):
    rows: list[ImportRow]
    errors: int
    preview_token: str
