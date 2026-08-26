"""Shared project paths for generated artifacts (flat output/ + reports/).

All PNG outputs should live under ``output/plots/``. Use subfolders for grouping:

- ``output/plots/matrix/`` — matrix-style / grid charts
- ``output/plots/perf/`` — performance / timing / benchmark charts
- ``output/plots/`` root — default charts from ``btc_price_paths.py`` and ``sata_valuation.py``
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"

# Tracked (committed) last-known-good Treasury curve — NOT under output/, which
# is entirely gitignored. Used as a fallback when a live FRED fetch fails (e.g.
# the network path from a given environment to FRED is slow/blocked), so the
# discount rate degrades to recent real data instead of a hardcoded constant.
YIELD_CURVE_FALLBACK_PATH = PROJECT_ROOT / "yield_curve_fallback.json"
# Same idea for Strategy's treasury scrape. GitHub Actions is 403'd by
# strategy.com; without a committed fallback the site snapshot writes null
# holdings and the Next.js production build fails type-checking.
MSTR_TREASURY_FALLBACK_PATH = PROJECT_ROOT / "mstr_treasury_fallback.json"
CACHE_DIR = OUTPUT_DIR / "cache"
REPORTS_DIR = PROJECT_ROOT / "reports"
PLOTS_DIR = OUTPUT_DIR / "plots"
PLOTS_MATRIX_DIR = PLOTS_DIR / "matrix"
PLOTS_PERF_DIR = PLOTS_DIR / "perf"


def ensure_output_dirs() -> None:
    """Create output/, cache/, reports/, and output/plots/ (+ matrix/perf) if missing."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_MATRIX_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_PERF_DIR.mkdir(parents=True, exist_ok=True)
