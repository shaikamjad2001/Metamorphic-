"""Loads the frozen snapshot. Every agent reads data through a Snapshot object, never from disk or network."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from functools import lru_cache

import pandas as pd

from backend import config

PRICE_COLUMNS = ("median_price", "average_price", "median_ppsf")


@dataclass(frozen=True)
class Snapshot:
    """records: Realtor.com ZIP x month listing records (prices in `currency_unit`).
    listings: Kaggle per-listing rows. macro: metro benchmarks (always USD). geo: ZIP metadata."""

    records: pd.DataFrame
    listings: pd.DataFrame
    macro: pd.DataFrame
    zip_zhvi: pd.DataFrame
    geo: dict
    manifest: dict = field(default_factory=dict)
    currency_unit: str = "USD"

    @property
    def months(self) -> list[str]:
        return sorted(self.records["month"].unique())

    @property
    def zipcodes(self) -> list[str]:
        return sorted(self.records["zipcode"].unique())

    def with_records(self, records: pd.DataFrame, currency_unit: str | None = None) -> "Snapshot":
        return replace(self, records=records, currency_unit=currency_unit or self.currency_unit)


@lru_cache(maxsize=1)
def load_snapshot(path: str = config.SNAPSHOT_DIR) -> Snapshot:
    rec = pd.read_csv(os.path.join(path, "dfw_zip_month.csv"), dtype={"zipcode": str})
    lst = pd.read_csv(os.path.join(path, "dfw_listings_kaggle.csv"), dtype={"zipcode": str}, low_memory=False)
    macro = pd.read_csv(os.path.join(path, "macro_monthly.csv"))
    zz = pd.read_csv(os.path.join(path, "zillow_zip_zhvi.csv"), dtype={"zipcode": str})
    with open(os.path.join(path, "zip_geo.json")) as f:
        geo = json.load(f)
    manifest = {}
    mpath = os.path.join(path, "MANIFEST.json")
    if os.path.exists(mpath):
        with open(mpath) as f:
            manifest = json.load(f)
    return Snapshot(records=rec, listings=lst, macro=macro, zip_zhvi=zz, geo=geo, manifest=manifest)


def month_add(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + k
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def window_months(end: str, n: int = config.WINDOW_MONTHS) -> list[str]:
    return [month_add(end, -i) for i in range(n - 1, -1, -1)]
