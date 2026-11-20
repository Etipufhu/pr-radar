"""Typed configuration loaded from YAML."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class Brand(BaseModel):
    id: str
    name: str
    query: str
    aliases: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)

    @property
    def match_terms(self) -> list[str]:
        return self.aliases or [self.name]


class Edition(BaseModel):
    hl: str
    gl: str
    ceid: str

    @property
    def language(self) -> str:
        return self.hl.split("-")[0].lower()


class GdeltSettings(BaseModel):
    enabled: bool = False
    max_records: int = Field(250, ge=1, le=250)
    time_budget_seconds: float = Field(180, gt=0)


class Settings(BaseModel):
    primary_brand: str
    lookback_days: int = Field(7, ge=1, le=30)
    brands: list[Brand]
    editions: list[Edition]
    topics: dict[str, list[str]] = Field(default_factory=dict)
    gdelt: GdeltSettings = Field(default_factory=GdeltSettings)
    # Outlets that only match by accident (e.g. unrelated sites), dropped everywhere.
    exclude_domains: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_brands(self) -> Settings:
        ids = [b.id for b in self.brands]
        if len(ids) != len(set(ids)):
            raise ValueError("brand ids must be unique")
        if self.primary_brand not in ids:
            raise ValueError(f"primary_brand {self.primary_brand!r} is not in brands")
        return self

    @property
    def brand_names(self) -> dict[str, str]:
        return {b.id: b.name for b in self.brands}


def load_config(path: str | Path) -> Settings:
    with open(path, encoding="utf-8") as fh:
        return Settings.model_validate(yaml.safe_load(fh))
