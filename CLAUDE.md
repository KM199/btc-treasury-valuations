# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

STRC Sim is a **Bitcoin Treasury Valuation System** that models and values SATA preferred stock issued by a Bitcoin Treasury Company. It runs Monte Carlo simulations of Bitcoin price paths over 100 years to determine dividend sustainability and NPV-based fair value per share.

## Environment Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Use a **single** local virtualenv at `venv/` (do not maintain a parallel `.venv/` — it duplicates hundreds of MB and divergent package sets). Matplotlib is configured for headless operation (`Agg` backend) — do not attempt to display plots interactively.

## Pipeline: How to Run

Generated artifacts use a flat **`output/`** directory (JSON, `.npy` / `.npz`, valuation results, PNG charts under `output/plots/`) and **`reports/`** for HTML deliverables. Paths are centralized in `strc_paths.py`.

The analysis runs in four sequential stages:

```bash
# 1. Fetch live market data (writes JSON under output/)
python fetch_data.py

# 2. Generate Bitcoin price paths (~1GB under output/, takes several minutes)
python btc_price_paths.py

# 3. Run the valuation engine (reads paths from output/ by default)
python sata_valuation.py [--data-dir output] [--output output/sata_valuation_results.json] \
    [--plots-dir output/plots] [--num-workers N] [--optimization-level 0|1|2] [--baseline-only]

# 4. Generate the HTML report (default: reports/sata_valuation_report.html)
python html_report_generator.py [--input output/sata_valuation_results.json] \
    [--output reports/sata_valuation_report.html]
```

`--optimization-level 2` (default) enables early termination for insolvent simulation paths, which dramatically reduces runtime.

## Architecture

### Data Flow

```
fetch_data.py
    → output/mstr_data.json, output/ibit_data.json, output/btc_historical_data.json, output/yield_curve.json, etc.

test_treasury_api.py
    → output/treasury_extracted_data.json  (BTCC holdings, cash, shares outstanding)

btc_price_paths.py
    → output/btc_price_paths_scenarios_price_paths.npy   (~1GB uncompressed)
    → output/btc_price_paths_scenarios_metadata.npz
    → output/plots/*.png

sata_valuation.py
    → reads treasury + price path files from output/
    → runs parallel Monte Carlo simulations (ProcessPoolExecutor)
    → output/sata_valuation_results.json
    → output/plots/*.png

html_report_generator.py
    → reports/sata_valuation_report.html (charts embedded as base64)
```

### Configuration System

All model parameters live in the `Configuration` class at the top of `sata_valuation.py`. At runtime, `setup_configuration_and_data()` overrides defaults with live values from `output/treasury_extracted_data.json` when present (bitcoin holdings, cash reserve, shares outstanding, current BTC price). When editing model parameters, change them in the `Configuration` class — not in individual functions.

### Simulation Architecture

`sata_valuation.py` runs four distinct analyses:
1. **Baseline**: 10,000 simulations at the current BTC price
2. **Multi-scenario**: Same 10,000 paths tested at 21 different BTC starting prices (±10%)
3. **Threshold sensitivity**: How the dividend suspension threshold multiplier affects NPV
4. **BTC credit ratio sensitivity**: Dynamic analysis based on current holdings ratio

The inner simulation loop (`simulate_dividend_path`) is JIT-compiled with Numba when available, falling back to pure Python silently. Parallel execution uses `ProcessPoolExecutor`; if multiprocessing fails it falls back to serial.

### Price Path File Format

`btc_price_paths.py` writes two files intentionally:
- `.npy` (uncompressed): fast memory-mapped loading of the 10,000 × 1,200-month price matrix
- `.npz` (compressed): scenario metadata and parameters

This split avoids decompression overhead on the large array at valuation time.

### Dividend Suspension Logic

Each monthly simulation step:
1. Calculate adjusted BTC credit = `(btc_holdings × price + cash) / total_par_value`
2. If credit > suspension threshold multiplier: attempt to pay dividend from cash, then sell BTC if needed
3. If insufficient: suspend dividend and start compounding unpaid amount (12.5%–20% annual, +25bps/month, capped at 20%)
4. Track cumulative NPV using pre-computed monthly discount factors

The suspension threshold multiplier is the key sensitivity parameter — tested from 0× to 2× par value.

## Key Files

| File | Purpose |
|------|---------|
| `strc_paths.py` | Default `output/`, `output/plots/`, and `reports/` path constants |
| `sata_valuation.py` | Main engine: Configuration class, simulation logic, all four analyses |
| `btc_price_paths.py` | Monte Carlo BTC price generation with manually tunable distribution parameters |
| `html_report_generator.py` | Reads results JSON, produces self-contained HTML report under `reports/` |
| `fetch_data.py` | Fetches live data from Yahoo Finance; writes JSON under `output/` |
| `test_treasury_api.py` | Treasury data fetcher → `output/treasury_extracted_data.json` |
| `output/treasury_extracted_data.json` | Runtime configuration source — overrides Configuration defaults when present |

## Distribution Parameters

Bitcoin price returns in `btc_price_paths.py` use a **manually tuned skewed distribution** (not auto-fitted). Top-of-file constants control the shape:
- `DIST_MEAN`, `DIST_STD`: base normal parameters
- `DIST_SKEW`: asymmetry (negative = left-skewed / bearish bias)
- Tail weight and kurtosis constants

Adjust these constants directly when recalibrating the model to current market conditions.

## Notebooks

Six Jupyter notebooks provide interactive exploration (`strc_valuation.ipynb`, `sata_playground.ipynb`, and others for IBIT/MSTR side analysis). **SATA valuation** is driven only by `sata_valuation.py` — there is no parallel `sata_valuation.ipynb`. The notebooks are not the authoritative computation — the `.py` scripts are.
