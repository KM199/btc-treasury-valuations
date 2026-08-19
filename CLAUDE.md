# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Human / portfolio docs:** [`docs/`](docs/) (overview, architecture, modules, valuation, capital-structure, data-sources) and [`README.md`](README.md). Prefer those for narrative; keep this file as agent ops.

## Project Overview

STRC Sim is a **Bitcoin Treasury Valuation System** that models and values SATA preferred stock issued by a Bitcoin Treasury Company. It runs Monte Carlo simulations of Bitcoin price paths over 100 years to determine dividend sustainability and NPV-based fair value per share. The portfolio UI lives under `web/`; site JSON is produced by `export_site_data.py`.

## Environment Setup

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

Use a **single** local virtualenv at `venv/` (do not maintain a parallel `.venv/` — it duplicates hundreds of MB and divergent package sets). In Cursor/VS Code, select **`…/STRC Sim/venv/bin/python`** so tests and notebooks use this environment. Matplotlib is configured for headless operation (`Agg` backend) — do not attempt to display plots interactively.

## Pipeline: How to Run

Generated artifacts use a flat **`output/`** directory (JSON, `.npy` / `.npz`, valuation results, PNG charts under `output/plots/`) and **`reports/`** for HTML deliverables. Paths are centralized in `strc_paths.py`.

The analysis runs in four sequential stages:

```bash
# 1. Fetch everything (Yahoo options, BTC history, yield curve, MSTR treasury, ASST/SATA, option deltas)
python fetch_data.py

# Optional: single-ticker or skip legs
# python fetch_data.py --only strc
# python fetch_data.py --skip-asst          # hedge-only (no SATA valuation inputs)
# python fetch_data.py --skip-deltas        # raw chains only (faster)
# python fetch_data.py --force-refresh      # bypass the 1-hour network cache
# python fetch_mstr_treasury.py             # standalone MSTR treasury refresh
# python fetch_asst_api.py                  # standalone ASST refresh
# python ibit_option_deltas.py              # standalone delta enrichment

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

## Website

```bash
python export_site_data.py   # → web/public/data/*.json
cd web && npm install && npm run dev
```

Human docs: [`docs/`](docs/). Site app: [`web/`](web/). CI: `.github/workflows/` (15-min market snapshot, daily valuation).

## Tests

```bash
# Run all tests
python -m pytest -v

# Model tests only — no fetched data required
python -m pytest test_dividend_waterfall.py -v

# Run a single test
python -m pytest test_ibit_option_deltas_convexity.py::TestIbitOptionDeltasConvexity::test_gamma_magnitude_atm_strike -v
```

`test_dividend_waterfall.py` tests the monthly dividend waterfall in `sata_valuation.py`: payment order (cash always, Bitcoin only above the gate), the suspension gate against `coverage_claim_value`, the certificate's compounded-dividend arrears mechanics (coupon +25bps, +25bps/month outstanding, 20% cap, compounded monthly on the whole balance), catch-up and clock reset, and the SATA-at-market-net-of-STRC claim. Builds its own configs — runs anywhere.

`test_ibit_option_deltas_convexity.py` tests the CRR binomial tree implementation in `ibit_option_deltas.py`: Greek magnitudes (Δ, Γ, ρ), convexity of parallel spot+rate shocks, and long-put P&L direction. Tests skip automatically if `output/ibit_data.json` is absent — but they **error** rather than skip if the file exists without delta enrichment (a raw chain has no `risk_free_rate`). Run `python ibit_option_deltas.py` to enrich it.

## Architecture

### Data Flow

```
fetch_data.py
    → output/mstr_data.json, output/strc_data.json, output/ibit_data.json, output/btc_historical_data.json, output/yield_curve.json, etc.
    (yield curve bootstrap: fetch_treasury_zero_yieldcurve.py)

fetch_data.py (full run) also calls:
    fetch_mstr_treasury.py → mstr_strategy_raw.json, mstr_treasury_extracted_data.json
    fetch_asst_api.py      → treasury_extracted_data.json  (ASST/SATA holdings, cash, shares)

btc_price_paths.py
    → output/btc_price_paths_scenarios_price_paths.npy   (~1GB uncompressed)
    → output/btc_price_paths_scenarios_metadata.npz
    → output/plots/*.png  (default charts; see also output/plots/matrix/, output/plots/perf/)

sata_valuation.py
    → reads treasury + price path files from output/
    → runs parallel Monte Carlo simulations (ProcessPoolExecutor)
    → output/sata_valuation_results.json
    → output/plots/*.png  (same layout: optional matrix/ and perf/ subfolders)

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
4. **Dividend rate sensitivity**: How the stated coupon rate affects NPV

The inner simulation loop (`simulate_dividend_path`) is JIT-compiled with Numba when available, falling back to pure Python silently. Parallel execution uses `ProcessPoolExecutor`; if multiprocessing fails it falls back to serial.

### Price Path File Format

`btc_price_paths.py` writes two files intentionally:
- `.npy` (uncompressed): fast memory-mapped loading of the 10,000 × 1,200-month price matrix
- `.npz` (compressed): scenario metadata and parameters

This split avoids decompression overhead on the large array at valuation time.

### Plot outputs

All raster charts belong under **`output/plots/`**. Defaults from `btc_price_paths.py` and `sata_valuation.py` land in that directory root. Use **`output/plots/matrix/`** for matrix-style figures and **`output/plots/perf/`** for performance / benchmark runs (`PLOTS_MATRIX_DIR` and `PLOTS_PERF_DIR` in `strc_paths.py`). Do not create new top-level `matrix_plots/` or `perf_plots/` folders.

### Dividend Suspension Logic

Each monthly simulation step:
1. Pay accumulated unpaid dividends from **cash first** (always); remaining balance from BTC only if BTC mark-to-market ≥ threshold (typically 1× the net claim)
2. Pay the current monthly dividend from **cash first** (always); sell BTC for any shortfall only if BTC mark-to-market ≥ threshold
3. If the full monthly dividend is not paid: the dividend is suspended and the unpaid amount compounds monthly at the coupon +25bps, stepping up another 25bps for each further unpaid month, capped at 20% annual (per the certificate of designation — `compounded_dividend_start_rate=None` tracks the live coupon)
4. Track cumulative NPV using pre-computed monthly discount factors

Cash is never blocked by the suspension threshold — only BTC sales are. The cash reserve runs to zero before any Bitcoin is sold.

The gate base is `Configuration.coverage_claim_value` = SATA marked at its live market price, less Strive's STRC holding marked at STRC's live price (`STRC_SHARES_HELD` in `preferred_valuation.py`, a 10-Q figure refreshed quarterly). Par is not used: SATA trades below its $100 stated amount, and the STRC position nets the claim down dollar for dollar without ever counting as cash. Dividends are still computed on gross par. The threshold multiplier (sensitivity-tested from 0× to 2×) gates Bitcoin liquidations only.

## Key Files

| File | Purpose |
|------|---------|
| `strc_paths.py` | `PROJECT_ROOT`, `OUTPUT_DIR`, `CACHE_DIR`, `REPORTS_DIR`, `PLOTS_DIR`, `PLOTS_MATRIX_DIR`, `PLOTS_PERF_DIR`, `ensure_output_dirs()` |
| `sata_valuation.py` | Main engine: Configuration class, simulation logic, all four analyses |
| `btc_price_paths.py` | Monte Carlo BTC price generation with manually tunable distribution parameters |
| `html_report_generator.py` | Reads results JSON, produces self-contained HTML report under `reports/` |
| `fetch_data.py` | Single entry point: Yahoo options, BTC history, yield curve, treasury, option deltas |
| `fetch_treasury_zero_yieldcurve.py` | FRED yields → bootstrapped Treasury zero curve (`build_treasury_zero_curve`); used by `fetch_data.py` and `ibit_option_deltas.py` |
| `fetch_asst_api.py` | ASST/SATA from strategytracker → `output/treasury_extracted_data.json` |
| `fetch_mstr_treasury.py` | MSTR treasury from strategy.com → `output/mstr_treasury_extracted_data.json` |
| `data_cache.py` | TTL-based network cache (1h default) stored under `output/cache/`; `get_or_fetch()` is the main entry point for all fetch scripts |
| `fetch_yahoo.py` | Shared cached Yahoo Finance helpers (`yahoo_spot_price`, `load_btc_spot`) used across fetch scripts |
| `mstr_hedge_helpers.py` | Shared helpers for `mstr_options_hedge.ipynb`: theta, hedge sizing, $10k book P&L shocks |
| `mstr_liquidation.py` | STRC liquidation waterfall math: senior-claim wipeout band and MSTR/STRC put-hedge sizing |
| `check_baseline.py` | Utility: verify that the baseline scenario is present in `output/sata_valuation_results.json` |
| `output/treasury_extracted_data.json` | Runtime configuration source — overrides Configuration defaults when present |

## Distribution Parameters

Bitcoin price returns in `btc_price_paths.py` use a **manually tuned skewed distribution** (not auto-fitted). Top-of-file constants control the shape:
- `DIST_MEAN`, `DIST_STD`: base normal parameters
- `DIST_SKEW`: asymmetry (negative = left-skewed / bearish bias)
- Tail weight and kurtosis constants

Adjust these constants directly when recalibrating the model to current market conditions.

## Notebooks

Six Jupyter notebooks provide interactive exploration (`strc_valuation.ipynb`, `sata_playground.ipynb`, and others for IBIT/MSTR side analysis). **SATA valuation** is driven only by `sata_valuation.py` — there is no parallel `sata_valuation.ipynb`. The notebooks are not the authoritative computation — the `.py` scripts are.
