from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=40)
    operator: Literal["gt", "gte", "lt", "lte", "between", "eq", "neq", "in", "not_in", "is_true", "is_false"]
    value: float | str | list[str] | None = None
    value2: float | None = None


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["and", "or"] = "and"
    conditions: list[Union["Group", Condition]] = Field(default_factory=list, max_length=20)


class Sort(BaseModel):
    field: str | None = None
    descending: bool = True


class ScreenDefinition(BaseModel):
    filter: Group = Field(default_factory=Group)
    sort: Sort = Field(default_factory=Sort)
    columns: list[str] = Field(default_factory=list, max_length=30)


class ScreenRequest(ScreenDefinition):
    as_of: date | None = Field(None, description="Screen on data up to this date (inclusive); default latest")
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)


class SavedScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    universe: Literal["equities", "funds"]
    definition: ScreenDefinition


class SavedScreenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    screen_id: str
    name: str
    universe: str
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime
