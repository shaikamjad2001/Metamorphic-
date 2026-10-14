"""Download every raw source ONCE into data/raw/ (gitignored, ~1.1 GB transient).

Run this only to rebuild the frozen snapshot from scratch. The app, the metamorphic harness
and every reported number read data/snapshot/ only, never the network.

Large national files (Realtor.com ZIP history ~840 MB, Zillow ZIP ZHVI ~120 MB) are streamed:
the SHA-256 of the full upstream file is computed on the fly while only the Dallas-area
rows (ZIP3 750-753) are written to disk.

Usage:  python scripts/fetch_raw_data.py
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")

DFW_ZIP3 = ("750", "751", "752", "753")
UA = {"User-Agent": "Mozilla/5.0 (TSE-coursework; reproducible data freeze)"}

SOURCES = {
    "realtor_zip_history": "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_Zip_History.csv",
    "kaggle_usa_real_estate": "https://www.kaggle.com/api/v1/datasets/download/ahmedshahriarsakib/usa-real-estate-dataset",
    "zillow_zip_zhvi": "https://files.zillowstatic.com/research/public_csvs/zhvi/Zip_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "zillow_metro_zhvi": "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
    "census_zcta_gazetteer": "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip",
}
FRED_SERIES = {
    "MEDLISPRI19100": "Realtor.com median listing price, Dallas-Fort Worth-Arlington MSA",
    "ACTLISCOU19100": "Realtor.com active listing count, Dallas-Fort Worth-Arlington MSA",
    "MEDLISPRIPERSQUFEE19100": "Realtor.com median listing price per sq ft, Dallas-Fort Worth-Arlington MSA",
    "MORTGAGE30US": "Freddie Mac 30-year fixed mortgage average (weekly)",
    "ATNHPIUS19124Q": "FHFA all-transactions HPI, Dallas-Plano-Irving MSAD (quarterly)",
}


def _open(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)


def download(url: str, dest: str) -> str:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    h = hashlib.sha256()
    with _open(url) as r, open(dest, "wb") as f:
        while block := r.read(1 << 20):
            h.update(block)
            f.write(block)
    print(f"  downloaded {os.path.relpath(dest, ROOT)} ({os.path.getsize(dest):,} bytes)")
    return h.hexdigest()


def stream_filter_csv(url: str, dest: str, keep) -> tuple[str, int, int]:
    """Stream a large CSV, hash every upstream byte, keep header + rows where keep(row_dict) is true."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    h = hashlib.sha256()

    class HashingReader(io.RawIOBase):
        def __init__(self, resp):
            self.resp = resp

        def readable(self):
            return True

        def readinto(self, b):
            data = self.resp.read(len(b))
            h.update(data)
            b[: len(data)] = data
            return len(data)

    total = kept = 0
    with _open(url) as resp:
        text = io.TextIOWrapper(io.BufferedReader(HashingReader(resp), 1 << 20), encoding="utf-8", newline="")
        reader = csv.DictReader(text)
        with open(dest, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                total += 1
                if keep(row):
                    writer.writerow(row)
                    kept += 1
        while text.buffer.read(1 << 20):
            pass
    print(f"  streamed {total:,} rows, kept {kept:,} -> {os.path.relpath(dest, ROOT)}")
    return h.hexdigest(), total, kept


def main() -> int:
    manifest = {"retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": {}}

    print("[1/6] Realtor.com Residential Listings Database, ZIP history (stream + filter ZIP3 750-753)")
    sha, total, kept = stream_filter_csv(
        SOURCES["realtor_zip_history"], os.path.join(RAW, "realtor", "rdc_zip_history_dfw.csv"),
        lambda r: str(r.get("postal_code", "")).zfill(5).startswith(DFW_ZIP3),
    )
    manifest["files"]["realtor/rdc_zip_history_dfw.csv"] = {
        "url": SOURCES["realtor_zip_history"], "upstream_sha256": sha, "upstream_rows": total, "kept_rows": kept}

    print("[2/6] Kaggle USA Real Estate (ahmedshahriarsakib/usa-real-estate-dataset)")
    zpath = os.path.join(RAW, "kaggle", "usa-real-estate-dataset.zip")
    sha = download(SOURCES["kaggle_usa_real_estate"], zpath)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(os.path.dirname(zpath))
    manifest["files"]["kaggle/usa-real-estate-dataset.zip"] = {"url": SOURCES["kaggle_usa_real_estate"], "sha256": sha}

    print("[3/6] Zillow ZHVI by ZIP (stream + filter)")
    sha, total, kept = stream_filter_csv(
        SOURCES["zillow_zip_zhvi"], os.path.join(RAW, "zillow", "zip_zhvi_dfw.csv"),
        lambda r: str(r.get("RegionName", "")).zfill(5).startswith(DFW_ZIP3) and r.get("State") == "TX",
    )
    manifest["files"]["zillow/zip_zhvi_dfw.csv"] = {
        "url": SOURCES["zillow_zip_zhvi"], "upstream_sha256": sha, "upstream_rows": total, "kept_rows": kept}

    print("[4/6] Zillow ZHVI by metro")
    dest = os.path.join(RAW, "zillow", "metro_zhvi.csv")
    manifest["files"]["zillow/metro_zhvi.csv"] = {"url": SOURCES["zillow_metro_zhvi"],
                                                  "sha256": download(SOURCES["zillow_metro_zhvi"], dest)}

    print("[5/6] FRED series")
    for sid, desc in FRED_SERIES.items():
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
        dest = os.path.join(RAW, "fred", f"{sid}.csv")
        manifest["files"][f"fred/{sid}.csv"] = {"url": url, "description": desc, "sha256": download(url, dest)}

    print("[6/6] US Census 2024 ZCTA gazetteer (ZIP centroids)")
    zpath = os.path.join(RAW, "census", "2024_Gaz_zcta_national.zip")
    sha = download(SOURCES["census_zcta_gazetteer"], zpath)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(os.path.dirname(zpath))
    manifest["files"]["census/2024_Gaz_zcta_national.zip"] = {"url": SOURCES["census_zcta_gazetteer"], "sha256": sha}

    with open(os.path.join(RAW, "raw_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("Done. Now run: python scripts/build_snapshot.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
