from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.common import Strict

ATC_RE = re.compile(r"^[A-Z]\d{2}[A-Z]{2}\d{2}$")
Level = Literal["minor", "moderate", "major", "contraindicated"]


class DoseRuleIn(Strict):
    population: str = Field(min_length=1, max_length=40)
    min_dose: float = Field(gt=0)
    max_dose: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=20)
    max_daily: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _order(self):
        if self.min_dose > self.max_dose:
            raise ValueError("min_dose maks dozadan katta bo'lmasligi kerak")
        return self


class ContraIn(Strict):
    text: str = Field(min_length=2, max_length=300)
    absolute: bool = False


class SideEffectIn(Strict):
    text: str = Field(min_length=2, max_length=300)
    frequency: Literal["common", "uncommon", "rare"] = "common"


class InteractionIn(Strict):
    drug_id: str = Field(min_length=1, max_length=100)  # uuid or drug_id or class:<name>
    drug_name: str | None = None
    level: Level
    mechanism: str = Field(min_length=2, max_length=500)
    recommendation: str = Field(min_length=2, max_length=500)


class SourceIn(Strict):
    title: str = Field(min_length=2, max_length=300)
    url: str = Field(max_length=500)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not re.match(r"^https?://\S+$", v):
            raise ValueError("url http(s):// bilan boshlanishi kerak")
        return v


class DrugIn(Strict):
    inn: str = Field(min_length=2, max_length=160)
    trade_names: list[str] = Field(default_factory=list, max_length=30)
    group: str = Field(min_length=2, max_length=80)
    atc_code: str | None = Field(default=None, max_length=10)
    forms: list[str] = Field(default_factory=list, max_length=20)
    indications_icd10: list[str] = Field(default_factory=list, max_length=50)
    dose_rules: list[DoseRuleIn] = Field(default_factory=list, max_length=30)
    contraindications: list[ContraIn] = Field(default_factory=list, max_length=50)
    side_effects: list[SideEffectIn] = Field(default_factory=list, max_length=50)
    interactions: list[InteractionIn] = Field(default_factory=list, max_length=200)
    sources: list[SourceIn] = Field(default_factory=list, max_length=30)

    @field_validator("atc_code")
    @classmethod
    def _atc(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        v = v.strip().upper()
        if not ATC_RE.match(v):
            raise ValueError("ATC kod formati: A12BC34")
        return v


class DrugListItemOut(Strict):
    id: UUID
    inn: str
    trade_names: list[str]
    group: str
    version: int
    status: Literal["draft", "published", "archived"]
    updated_at: str


class ImportErrorOut(Strict):
    row: int
    message: str


class ImportReportOut(Strict):
    total: int
    valid: int
    errors: list[ImportErrorOut]
    created: int = 0
    dry_run: bool = True
