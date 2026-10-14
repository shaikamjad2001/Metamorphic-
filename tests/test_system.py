import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest

from backend import config
from backend.pipeline import run_pipeline
from backend.schemas import SearchCriteria
from backend.snapshot import load_snapshot
from backend.stats import bootstrap_weighted_medians, weighted_median, wilson_interval
from backend.tools import StratifiedMedianTool
from mt.base_inputs import load_base_inputs
from mt.harness import run_case


@pytest.fixture(scope="module")
def snap():
    return load_snapshot()


@pytest.fixture(scope="module")
def bases():
    return load_base_inputs()


def _base(bases, label_prefix):
    return next(b for b in bases if b.label.startswith(label_prefix))


def test_snapshot_matches_manifest():
    with open(os.path.join(config.SNAPSHOT_DIR, "MANIFEST.json")) as f:
        manifest = json.load(f)
    for name, digest in manifest["snapshot_sha256"].items():
        with open(os.path.join(config.SNAPSHOT_DIR, name), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == digest, name
    assert manifest["synthetic_or_imputed_values"] == "none"


def test_weighted_median_is_order_invariant_and_scale_equivariant():
    rng = np.random.default_rng(0)
    v, w = rng.uniform(1e5, 9e5, 50), rng.integers(1, 200, 50).astype(float)
    m = weighted_median(v, w)
    perm = rng.permutation(50)
    assert weighted_median(v[perm], w[perm]) == m
    assert weighted_median(v * 1.25, w) == pytest.approx(m * 1.25, rel=1e-12)
    assert weighted_median(np.concatenate([v, v]), np.concatenate([w, w])) == m
    assert weighted_median([1, 2, 3], [1, 1, 10]) == 3


def test_bootstrap_ignores_input_order():
    v, w = np.array([5.0, 1.0, 3.0, 9.0]), np.array([2.0, 7.0, 1.0, 4.0])
    a = bootstrap_weighted_medians(v, w, np.random.default_rng(7), 50)
    b = bootstrap_weighted_medians(v[::-1], w[::-1], np.random.default_rng(7), 50)
    assert np.array_equal(a, b)


def test_wilson_interval_reference_values():
    lo, hi = wilson_interval(0, 96)
    assert lo == 0.0 and hi == pytest.approx(0.0384, abs=1e-4)
    lo, hi = wilson_interval(18, 96)
    assert (lo, hi) == (pytest.approx(0.1220, abs=1e-4), pytest.approx(0.2770, abs=1e-4))


def test_zip_ranking_tolerates_duplicate_records():
    """Regression: MR2 found zip_rankings crashing on duplicated ZIP-month rows."""
    df = pd.DataFrame({"zipcode": ["75201", "75201", "75202", "75202"] * 2,
                       "month": ["2025-01"] * 4 + ["2025-12"] * 4,
                       "median_price": [100.0, 100.0, 200.0, 200.0, 110.0, 110.0, 190.0, 190.0],
                       "active_count": [5] * 8})
    rows = StratifiedMedianTool.zip_rankings(df, df["median_price"], "2025-01", "2025-12", {})
    assert [r["zipcode"] for r in rows] == ["75201", "75202"]
    assert rows[0]["change_pct"] == pytest.approx(10.0)


def test_pipeline_is_deterministic_for_a_seed(snap, bases):
    b = _base(bases, "B07")
    r1, r2 = run_pipeline(b, snap, 42), run_pipeline(b, snap, 42)
    assert r1.trend.model_dump() == r2.trend.model_dump()


def test_both_loops_fire_and_are_bounded(snap, bases):
    r = run_pipeline(_base(bases, "B07"), snap, 42)
    assert 1 <= r.diagnostics["feedback_cycles"] <= config.MAX_FEEDBACK_CYCLES
    assert 1 <= r.diagnostics["refinement_cycles"] <= config.MAX_REFINEMENT_CYCLES
    loops = {e.loop for e in r.events}
    assert {"feedback", "refinement"} <= loops


def test_pinned_replay_reproduces_source(snap, bases):
    b = _base(bases, "B13")
    src = run_pipeline(b, snap, 101)
    rep = run_pipeline(b, snap, 101, forced=src.control)
    assert [m.median_price for m in rep.trend.monthly_series] == [m.median_price for m in src.trend.monthly_series]


def test_degraded_delivery_does_not_crash(snap):
    r = run_pipeline(SearchCriteria(zipcodes=["75201"], min_price=900000, max_price=950000), snap, 42)
    assert r.trend.confidence <= config.DEGRADED_CONFIDENCE_CAP
    assert r.caveats


@pytest.mark.parametrize("mr", ["MR1", "MR3", "MR8"])
def test_invariance_relations_hold_on_samples(mr):
    for b in (0, 6, 30):
        assert run_case(mr, b, 42, "natural")["violated"] is False


def test_trim_guard_regression():
    """Regression: MR4 (pinned) found the MAD trim dropping the heaviest record in a 4-ZIP month."""
    r = run_case("MR4R", 27, 2026, "pinned")
    assert r["violated"] in (False, None)


def test_criteria_validation():
    with pytest.raises(ValueError):
        SearchCriteria(min_price=5, max_price=1)
    with pytest.raises(ValueError):
        SearchCriteria(window_end="2025-13")
