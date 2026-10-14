"""Agent 1: normalises user criteria into a validated, fully resolved query (pipeline entry point)."""
from __future__ import annotations

from dataclasses import dataclass

from backend.agents.base import Trace
from backend.schemas import SearchCriteria
from backend.snapshot import Snapshot, month_add, window_months
from backend.tools import Bands


class CriteriaError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedQuery:
    criteria: SearchCriteria
    zips: tuple[str, ...]
    months: tuple[str, ...]
    context_months: tuple[str, ...]
    bands: Bands


class Orchestrator:
    name = "Orchestrator"

    def normalize(self, criteria: SearchCriteria, snapshot: Snapshot, trace: Trace) -> NormalizedQuery:
        if criteria.currency_unit != snapshot.currency_unit:
            raise CriteriaError(f"criteria are in {criteria.currency_unit} but the snapshot is in {snapshot.currency_unit}")
        universe = set(snapshot.zipcodes)
        zips = set(universe)
        if criteria.zipcodes:
            unknown = sorted(set(criteria.zipcodes) - universe)
            zips &= set(criteria.zipcodes)
            if unknown:
                trace.log(self.name, "ignored_unknown_zips", zips=unknown)
        if criteria.cities:
            wanted = {c.strip().lower() for c in criteria.cities}
            zips &= {z for z in universe if (snapshot.geo.get(z, {}).get("city") or "").lower() in wanted}
        if criteria.tiers:
            wanted = {t.strip().lower() for t in criteria.tiers}
            zips &= {z for z in universe if snapshot.geo.get(z, {}).get("price_tier", "").lower() in wanted}
        if not zips:
            raise CriteriaError("no ZIP codes in the snapshot match the ZIP / city / tier criteria")

        months = window_months(criteria.window_end)
        available = snapshot.months
        if months[0] < available[0] or months[-1] > available[-1]:
            raise CriteriaError(f"12-month window {months[0]}..{months[-1]} is outside the snapshot "
                                f"({available[0]}..{available[-1]})")
        context = [m for m in [month_add(months[0], -2), month_add(months[0], -1)] + months
                   + [month_add(months[-1], 1), month_add(months[-1], 2)] if available[0] <= m <= available[-1]]

        bands = Bands(criteria.min_price, criteria.max_price, criteria.min_sqft, criteria.max_sqft)
        q = NormalizedQuery(criteria=criteria, zips=tuple(sorted(zips)), months=tuple(months),
                            context_months=tuple(context), bands=bands)
        trace.log(self.name, "normalized_criteria", n_zips=len(q.zips), window=[months[0], months[-1]],
                  bands=bands.__dict__, currency_unit=criteria.currency_unit)
        return q
