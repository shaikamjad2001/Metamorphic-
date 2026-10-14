"""Single place for every tunable constant. Values are recorded in each RunResult for traceability."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_DIR = os.path.join(ROOT, "data", "snapshot")
RESULTS_DIR = os.path.join(ROOT, "results")

WINDOW_MONTHS = 12
DEFAULT_WINDOW_END = "2026-09"

# Quality Auditor (feedback loop). The brief's "N >= 10 active listings per month" is translated to
# ZIP-level records: a month is adequately covered when it has enough distinct ZIP submarkets AND
# enough active listings behind them.
MIN_ZIPS_PER_MONTH = 4
MIN_ACTIVE_PER_MONTH = 40
RELAXATION_SCHEDULE = (0.15, 0.30, 0.45)
SPATIAL_EXPANSION_STEP = 2
MAX_FEEDBACK_CYCLES = 3

# Trend Specialist (method switch).
HEDONIC_SQFT_CV_THRESHOLD = 0.30
HEDONIC_BED_SIGMA_THRESHOLD = 0.50
HEDONIC_BASE_SQFT = 1800.0
HEDONIC_ELASTICITY = 0.75
EXTREME_SPARSITY_ZIPS = 2

# Synthesizer (conditional iteration).
CONFIDENCE_TARGET = 0.85
BOOTSTRAP_RESAMPLES = 200
STABILITY_SCALE = 0.35
RELAXATION_PENALTY = 0.04
DEGRADED_CONFIDENCE_CAP = 0.59
MAX_REFINEMENT_CYCLES = 3
REFINEMENT_SEQUENCE = ("robust_trim", "temporal_pool_3", "temporal_pool_5")
ROBUST_TRIM_MAD = 3.5
# A MAD estimated from a handful of ZIP medians is unstable: one record's small shift can flip it
# across the cut-off and remove the heaviest-weighted record. Months with fewer records are not trimmed.
ROBUST_TRIM_MIN_RECORDS = 8

# Loop Supervisor.
WALL_CLOCK_BUDGET_S = 12.0

# Data hygiene: ZIP-month medians below this (in USD) are treated as data errors. Scaled by the
# active currency unit so that a USD -> USD-thousands conversion does not change which rows survive.
MIN_VALID_PRICE_USD = 10_000.0

CURRENCY_FACTORS = {"USD": 1.0, "USD_K": 0.001}

SEEDS = (42, 101, 2026)
