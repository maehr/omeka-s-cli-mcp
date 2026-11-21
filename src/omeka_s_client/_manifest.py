"""Validation for snapshot metadata."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Count = Annotated[int, Field(ge=0)]


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    source: str | None = None
    items_count: Count | None = None
    media_count: Count | None = None
