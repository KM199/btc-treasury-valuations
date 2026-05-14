"""Shared project paths for generated artifacts (flat output/ + reports/)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
REPORTS_DIR = PROJECT_ROOT / "reports"
PLOTS_DIR = OUTPUT_DIR / "plots"


def ensure_output_dirs() -> None:
    """Create output/, reports/, and output/plots/ if missing."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
