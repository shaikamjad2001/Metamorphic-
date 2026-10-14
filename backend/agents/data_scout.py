"""Agent 2: slices the frozen snapshot for the current plan. Target of the auditor's feedback loop."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from backend import config
from backend.agents.base import Trace
from backend.agents.orchestrator import NormalizedQuery
from backend.snapshot import Snapshot
from backend.tools import Bands, CompositionProfileTool, ListingFilterTool, MacroLookupTool


@dataclass
class ScanPlan:
    relaxation_level: int = 0
    added_zips: list[str] = field(default_factory=list)

    @property
    def relaxation_factor(self) -> float:
        return 0.0 if self.relaxation_level == 0 else config.RELAXATION_SCHEDULE[self.relaxation_level - 1]


@dataclass
class ScanResult:
    plan: ScanPlan
    zips: list[str]
    bands: Bands
    records: pd.DataFrame
    window_records: pd.DataFrame
    excluded_by_bands: int
    composition: dict
    macro: dict


_COMPOSITION_CACHE: dict[tuple, dict] = {}


def _composition(snapshot: Snapshot, zips: tuple[str, ...]) -> dict:
    key = (id(snapshot.listings), zips)
    if key not in _COMPOSITION_CACHE:
        _COMPOSITION_CACHE[key] = CompositionProfileTool.run(snapshot, list(zips))
    return _COMPOSITION_CACHE[key]


class DataScout:
    name = "DataScout"

    def scan(self, snapshot: Snapshot, q: NormalizedQuery, plan: ScanPlan, trace: Trace,
             iteration: int) -> ScanResult:
        zips = sorted(set(q.zips) | set(plan.added_zips))
        bands = q.bands.relaxed(plan.relaxation_factor) if plan.relaxation_level else q.bands
        recs = ListingFilterTool.run(snapshot, zips, list(q.context_months), bands)
        window = recs[recs["month"].isin(q.months)]
        excluded = ListingFilterTool.excluded_by_bands(snapshot, zips, list(q.months), bands)
        comp = _composition(snapshot, tuple(zips))
        macro = MacroLookupTool.run(snapshot, list(q.months), zips)
        trace.log(self.name, "scanned_snapshot", loop="feedback" if iteration else None, iteration=iteration,
                  tool=ListingFilterTool.name, relaxation_level=plan.relaxation_level,
                  relaxation_factor=plan.relaxation_factor, n_zips_in_scope=len(zips),
                  added_zips=list(plan.added_zips), records_in_window=int(len(window)),
                  active_listings_in_window=int(window["active_count"].sum()), excluded_by_bands=int(excluded),
                  kaggle_listings_profiled=comp["n_listings"])
        return ScanResult(plan=plan, zips=zips, bands=bands, records=recs, window_records=window,
                          excluded_by_bands=excluded, composition=comp, macro=macro)

    def nearest_zips(self, snapshot: Snapshot, selected: list[str], k: int) -> list[str]:
        """Spatial relaxation: the k unselected ZIPs closest to the selection's centroid."""
        geo = snapshot.geo
        pts = [(geo[z]["lat"], geo[z]["lon"]) for z in selected if z in geo]
        if not pts:
            return []
        clat = sum(p[0] for p in pts) / len(pts)
        clon = sum(p[1] for p in pts) / len(pts)
        cands = []
        for z in snapshot.zipcodes:
            if z in selected or z not in geo:
                continue
            d = math.hypot(geo[z]["lat"] - clat, (geo[z]["lon"] - clon) * math.cos(math.radians(clat)))
            cands.append((d, z))
        cands.sort()
        return [z for _, z in cands[:k]]
