"""Typed contracts. TrendOutput is the output contract every metamorphic relation is stated against."""
from __future__ import annotations

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend import config

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class SearchCriteria(BaseModel):
    """User-facing criteria. Price bounds apply to each ZIP-month median list price, sqft bounds to its median size."""

    zipcodes: Optional[list[str]] = None
    cities: Optional[list[str]] = None
    tiers: Optional[list[str]] = None
    min_price: Optional[float] = Field(default=None, ge=0)
    max_price: Optional[float] = Field(default=None, ge=0)
    min_sqft: Optional[float] = Field(default=None, ge=0)
    max_sqft: Optional[float] = Field(default=None, ge=0)
    window_end: str = config.DEFAULT_WINDOW_END
    currency_unit: Literal["USD", "USD_K"] = "USD"
    confidence_target: float = Field(default=config.CONFIDENCE_TARGET, gt=0, le=1)
    label: Optional[str] = None

    @field_validator("window_end")
    @classmethod
    def _month(cls, v: str) -> str:
        if not MONTH_RE.match(v):
            raise ValueError("window_end must be YYYY-MM")
        return v

    @field_validator("zipcodes")
    @classmethod
    def _zips(cls, v):
        if v is None:
            return v
        out = []
        for z in v:
            z = str(z).strip().zfill(5)
            if not re.fullmatch(r"\d{5}", z):
                raise ValueError(f"invalid ZIP {z!r}")
            out.append(z)
        return out

    @model_validator(mode="after")
    def _bands(self):
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price must be <= max_price")
        if self.min_sqft is not None and self.max_sqft is not None and self.min_sqft > self.max_sqft:
            raise ValueError("min_sqft must be <= max_sqft")
        return self


class MonthlyStat(BaseModel):
    month: str
    active_count: int
    n_zips: int
    median_price: Optional[float]
    median_price_per_sqft: Optional[float]
    price_q1: Optional[float]
    price_q3: Optional[float]
    new_listings: int
    median_dom: Optional[float]
    mom_pct_price: Optional[float]


class ZipTrend(BaseModel):
    zipcode: str
    city: Optional[str]
    start_price: float
    end_price: float
    change_pct: float
    end_active: int
    rank: int


class TrendOutput(BaseModel):
    """The 12-month trend. MRs compare these fields between a source and a follow-up run."""

    window_start: str
    window_end: str
    currency_unit: str
    method: Literal["hedonic", "stratified_median"]
    monthly_series: list[MonthlyStat]
    trend_change_pct: Optional[float]
    annual_cagr_estimate: Optional[float]
    macro_divergence_score: Optional[float]
    zip_rankings: list[ZipTrend]
    confidence: float
    quality_audit_passed: bool


class AgentEvent(BaseModel):
    step: int
    agent: str
    action: str
    loop: Optional[Literal["feedback", "refinement"]] = None
    iteration: Optional[int] = None
    detail: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: float = 0.0


class ControlPlan(BaseModel):
    """Every control decision the loops made. Re-applying it (pinned mode) replays the same path."""

    relaxation_level: int = 0
    relaxation_factor: float = 0.0
    added_zips: list[str] = Field(default_factory=list)
    method: Literal["hedonic", "stratified_median"] = "stratified_median"
    refinements: list[str] = Field(default_factory=list)


class RunResult(BaseModel):
    criteria: SearchCriteria
    seed: int
    trend: TrendOutput
    control: ControlPlan
    events: list[AgentEvent]
    caveats: list[str]
    narrative: str
    diagnostics: dict[str, Any]
