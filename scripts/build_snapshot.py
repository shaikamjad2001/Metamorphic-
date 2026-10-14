"""Freeze the real raw downloads (data/raw/) into the committed snapshot (data/snapshot/).

Every value in data/snapshot/ is copied or filtered from a real public source. Nothing is
simulated, imputed or interpolated. Missing upstream values stay missing (empty cells).

Outputs
  data/snapshot/dfw_zip_month.csv      Realtor.com ZIP x month listing records (what the agents scan)
  data/snapshot/dfw_listings_kaggle.csv Kaggle USA Real Estate per-listing rows for the same ZIPs
  data/snapshot/macro_monthly.csv      Zillow metro ZHVI + FRED (Realtor.com MSA, mortgage) + FHFA HPI
  data/snapshot/zillow_zip_zhvi.csv    Zillow ZHVI by ZIP x month (long format)
  data/snapshot/zip_geo.json           ZIP -> city, Census centroid, distance, price tier
  data/snapshot/MANIFEST.json          provenance, filters and SHA-256 of every snapshot file

Usage:  python scripts/build_snapshot.py
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "snapshot")

FIRST_MONTH, LAST_MONTH = "2022-12", "2026-09"
DOWNTOWN_DALLAS = (32.7767, -96.7970)
RADIUS_MILES = 40.0

# Named submarkets carried over from the design brief (10 core Dallas ZIPs).
CORE_ZIPS = {
    "75201": ("Downtown / Arts District", "Urban Core"),
    "75202": ("Downtown Historic", "Urban Core"),
    "75204": ("Uptown / State Thomas", "Mid-Market Residential"),
    "75206": ("Lower Greenville / M Streets", "Mid-Market Residential"),
    "75214": ("Lakewood", "Mid-Market Residential"),
    "75219": ("Oak Lawn / Turtle Creek", "Mid-Market Residential"),
    "75205": ("Highland Park / University Park", "Luxury Single-Family"),
    "75209": ("Bluffview / Inwood", "Luxury Single-Family"),
    "75225": ("Preston Hollow", "Luxury Single-Family"),
    "75230": ("North Dallas / Forest Hills", "Luxury Single-Family"),
}
TIER_LABELS = ["Entry", "Value", "Mid-Market", "Upper", "Luxury"]

REALTOR_COLS = {
    "median_listing_price": "median_price",
    "active_listing_count": "active_count",
    "median_listing_price_per_square_foot": "median_ppsf",
    "median_square_feet": "median_sqft",
    "new_listing_count": "new_listings",
    "pending_listing_count": "pending_listings",
    "price_reduced_count": "price_reduced",
    "median_days_on_market": "median_dom",
    "average_listing_price": "average_price",
    "total_listing_count": "total_listings",
    "quality_flag": "quality_flag",
}


def haversine_miles(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def month_str(yyyymm) -> str:
    s = str(int(yyyymm))
    return f"{s[:4]}-{s[4:]}"


def load_centroids() -> pd.DataFrame:
    path = os.path.join(RAW, "census", "2024_Gaz_zcta_national.txt")
    g = pd.read_csv(path, sep="\t", dtype={"GEOID": str})
    g.columns = [c.strip() for c in g.columns]
    g = g.rename(columns={"GEOID": "zipcode", "INTPTLAT": "lat", "INTPTLONG": "lon"})
    return g[["zipcode", "lat", "lon"]]


def build_zip_month(centroids: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    r = pd.read_csv(os.path.join(RAW, "realtor", "rdc_zip_history_dfw.csv"), dtype={"postal_code": str})
    r = r[pd.to_numeric(r["month_date_yyyymm"], errors="coerce").notna()].copy()
    r["zipcode"] = r["postal_code"].str.zfill(5)
    r["month"] = r["month_date_yyyymm"].map(month_str)
    r = r[(r["month"] >= FIRST_MONTH) & (r["month"] <= LAST_MONTH)]

    names = (r.dropna(subset=["zip_name"]).sort_values("month")
             .groupby("zipcode")["zip_name"].last().str.split(",").str[0].str.title())
    r["city"] = r["zipcode"].map(names)

    r = r.merge(centroids, on="zipcode", how="left")
    no_centroid = sorted(r.loc[r["lat"].isna(), "zipcode"].unique())
    r = r.dropna(subset=["lat", "lon"])
    r["distance_mi"] = [haversine_miles(*DOWNTOWN_DALLAS, a, b) for a, b in zip(r["lat"], r["lon"])]
    outside = sorted(r.loc[r["distance_mi"] > RADIUS_MILES, "zipcode"].unique())
    r = r[r["distance_mi"] <= RADIUS_MILES]

    n_before = len(r)
    r = r[r["median_listing_price"].notna() & (r["active_listing_count"] > 0)]
    dropped_empty = n_before - len(r)

    df = r[["zipcode", "month", "city"] + list(REALTOR_COLS)].rename(columns=REALTOR_COLS)
    df["record_id"] = "RDC-" + df["zipcode"] + "-" + df["month"]
    df["quality_flag"] = df["quality_flag"].fillna(0).astype(int)
    for c in ("active_count", "new_listings", "price_reduced", "total_listings"):
        df[c] = df[c].astype(int)
    df = df[["record_id", "zipcode", "city", "month"] + [c for c in REALTOR_COLS.values()]]
    df = df.sort_values(["month", "zipcode"]).reset_index(drop=True)
    filters = {
        "zip3_prefixes": ["750", "751", "752", "753"],
        "months": [FIRST_MONTH, LAST_MONTH],
        "radius_miles_from_downtown_dallas": RADIUS_MILES,
        "downtown_dallas_latlon": DOWNTOWN_DALLAS,
        "dropped_zips_outside_radius": outside,
        "dropped_zips_without_census_centroid": no_centroid,
        "dropped_rows_missing_price_or_zero_active": int(dropped_empty),
    }
    return df, filters


def build_geo(zm: pd.DataFrame, centroids: pd.DataFrame) -> dict:
    latest = zm[zm["month"] > "2025-09"]
    level = latest.groupby("zipcode")["median_price"].median()
    qs = level.quantile([0.2, 0.4, 0.6, 0.8]).values
    geo = {}
    cent = centroids.set_index("zipcode")
    for z in sorted(zm["zipcode"].unique()):
        lat, lon = float(cent.loc[z, "lat"]), float(cent.loc[z, "lon"])
        tier = TIER_LABELS[int(np.searchsorted(qs, level.get(z, np.nan)))] if z in level else "Unrated"
        nb, sub = CORE_ZIPS.get(z, (None, None))
        city = zm.loc[zm["zipcode"] == z, "city"].dropna()
        geo[z] = {
            "zipcode": z,
            "city": city.iloc[0] if len(city) else None,
            "neighborhood": nb,
            "core_submarket": sub,
            "price_tier": tier,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "distance_mi": round(haversine_miles(*DOWNTOWN_DALLAS, lat, lon), 2),
        }
    return geo


def build_kaggle(zips: set[str]) -> tuple[pd.DataFrame, dict]:
    k = pd.read_csv(os.path.join(RAW, "kaggle", "realtor-data.zip.csv"), low_memory=False)
    k = k[(k["state"] == "Texas") & k["zip_code"].notna()].copy()
    k["zipcode"] = k["zip_code"].astype(int).astype(str).str.zfill(5)
    k = k[k["zipcode"].isin(zips)]
    n_raw = len(k)
    k = k.drop_duplicates(subset=["street", "zipcode", "price", "status", "prev_sold_date"])
    n_dedup = len(k)
    out = pd.DataFrame({
        "listing_id": ["KGL-%06d" % i for i in range(len(k))],
        "status": k["status"].values,
        "price": k["price"].values,
        "bedrooms": k["bed"].values,
        "bathrooms": k["bath"].values,
        "sqft": k["house_size"].values,
        "acre_lot": k["acre_lot"].values,
        "city": k["city"].values,
        "zipcode": k["zipcode"].values,
        "prev_sold_date": k["prev_sold_date"].values,
    })
    out["price_per_sqft"] = np.where(out["sqft"] > 0, (out["price"] / out["sqft"]).round(2), np.nan)
    return out, {"rows_in_selected_zips": int(n_raw), "rows_after_exact_duplicate_drop": int(n_dedup),
                 "note": "Exact duplicate rows (same street, zip, price, status, prev_sold_date) dropped. No imputation."}


def build_macro() -> pd.DataFrame:
    months = pd.period_range(FIRST_MONTH, LAST_MONTH, freq="M").astype(str)
    macro = pd.DataFrame({"month": months})

    z = pd.read_csv(os.path.join(RAW, "zillow", "metro_zhvi.csv"))
    row = z[z["RegionName"] == "Dallas, TX"]
    if row.empty:
        row = z[z["RegionName"].str.startswith("Dallas", na=False)]
    row = row.iloc[0]
    zcols = {c[:7]: c for c in z.columns if c[:4].isdigit()}
    macro["zhvi_metro"] = [round(float(row[zcols[m]]), 2) if m in zcols and pd.notna(row[zcols[m]]) else np.nan for m in months]

    def fred(sid: str, how: str = "first") -> dict:
        f = pd.read_csv(os.path.join(RAW, "fred", f"{sid}.csv"))
        f["month"] = f["observation_date"].str[:7]
        f[sid] = pd.to_numeric(f[sid], errors="coerce")
        return f.groupby("month")[sid].agg(how).to_dict()

    macro["fred_median_listing_price"] = macro["month"].map(fred("MEDLISPRI19100"))
    macro["fred_active_listing_count"] = macro["month"].map(fred("ACTLISCOU19100"))
    macro["fred_median_ppsf"] = macro["month"].map(fred("MEDLISPRIPERSQUFEE19100"))
    macro["mortgage_rate_30y"] = macro["month"].map(fred("MORTGAGE30US", "mean")).round(3)
    fhfa = fred("ATNHPIUS19124Q")
    macro["fhfa_hpi_quarterly"] = macro["month"].map(fhfa)
    return macro


def build_zip_zhvi(zips: set[str]) -> pd.DataFrame:
    z = pd.read_csv(os.path.join(RAW, "zillow", "zip_zhvi_dfw.csv"), dtype={"RegionName": str})
    z["zipcode"] = z["RegionName"].str.zfill(5)
    z = z[z["zipcode"].isin(zips)]
    cols = [c for c in z.columns if c[:4].isdigit() and FIRST_MONTH <= c[:7] <= LAST_MONTH]
    long = z.melt(id_vars=["zipcode"], value_vars=cols, var_name="date", value_name="zhvi")
    long["month"] = long["date"].str[:7]
    long = long.dropna(subset=["zhvi"])
    long["zhvi"] = long["zhvi"].round(2)
    return long[["zipcode", "month", "zhvi"]].sort_values(["zipcode", "month"]).reset_index(drop=True)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    centroids = load_centroids()
    zm, zm_filters = build_zip_month(centroids)
    zips = set(zm["zipcode"])
    geo = build_geo(zm, centroids)
    kaggle, kaggle_notes = build_kaggle(zips)
    macro = build_macro()
    zzhvi = build_zip_zhvi(zips)

    files = {
        "dfw_zip_month.csv": zm,
        "dfw_listings_kaggle.csv": kaggle,
        "macro_monthly.csv": macro,
        "zillow_zip_zhvi.csv": zzhvi,
    }
    for name, df in files.items():
        df.to_csv(os.path.join(OUT, name), index=False)
        print(f"  {name}: {len(df):,} rows")
    with open(os.path.join(OUT, "zip_geo.json"), "w") as f:
        json.dump(geo, f, indent=1)

    raw_manifest = {}
    rm_path = os.path.join(RAW, "raw_manifest.json")
    if os.path.exists(rm_path):
        with open(rm_path) as f:
            raw_manifest = json.load(f)

    manifest = {
        "snapshot_version": "dfw-real-2026-10",
        "all_values_real": True,
        "synthetic_or_imputed_values": "none",
        "months": [FIRST_MONTH, LAST_MONTH],
        "n_zipcodes": len(zips),
        "sources": {
            "dfw_zip_month.csv": {
                "source": "Realtor.com Residential Listings Database, ZIP-level monthly inventory (RDC_Inventory_Core_Metrics_Zip_History.csv)",
                "unit": "one row = one ZIP code in one month; active_count = active for-sale listings in that ZIP-month",
                "filters": zm_filters,
                "license_note": "Public research data published by Realtor.com Economic Research; cite as Realtor.com Economic Research.",
            },
            "dfw_listings_kaggle.csv": {
                "source": "Kaggle: ahmedshahriarsakib/usa-real-estate-dataset (realtor-data.zip.csv, Realtor.com listings scraped 2021-2022)",
                "unit": "one row = one listing (for_sale / sold / ready_to_build)",
                "filters": kaggle_notes,
                "use_in_system": "Listing-level composition profile (bedroom and size mix per ZIP) used by the Trend Specialist's method switch and shown in the Listing Explorer. Not used as a time series because its real dates span only Nov 2021-Apr 2022.",
            },
            "macro_monthly.csv": {
                "zhvi_metro": "Zillow ZHVI (all homes, mid-tier, smoothed, seasonally adjusted), Dallas-Fort Worth-Arlington metro",
                "fred_median_listing_price": "FRED MEDLISPRI19100 (Realtor.com), DFW MSA",
                "fred_active_listing_count": "FRED ACTLISCOU19100 (Realtor.com), DFW MSA",
                "fred_median_ppsf": "FRED MEDLISPRIPERSQUFEE19100 (Realtor.com), DFW MSA",
                "mortgage_rate_30y": "FRED MORTGAGE30US, monthly mean of weekly values",
                "fhfa_hpi_quarterly": "FRED ATNHPIUS19124Q (FHFA all-transactions HPI, Dallas-Plano-Irving MSAD); only quarter-start months populated",
            },
            "zillow_zip_zhvi.csv": {"source": "Zillow ZHVI by ZIP (all homes, mid-tier, smoothed, SA)"},
            "zip_geo.json": {"source": "US Census Bureau 2024 Gazetteer ZCTA internal points; tier = quintile of the ZIP's median listing price over the latest 12 months"},
        },
        "raw_download_manifest": raw_manifest,
        "snapshot_sha256": {name: sha256(os.path.join(OUT, name)) for name in list(files) + ["zip_geo.json"]},
    }
    with open(os.path.join(OUT, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Snapshot frozen in {os.path.relpath(OUT, ROOT)}/ ({len(zips)} ZIPs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
