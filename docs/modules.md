# Modules

Flat repo: one concern per file. Prefer extending these over copying logic into notebooks.

## Shared infrastructure

| File | Owns |
|------|------|
| `strc_paths.py` | `PROJECT_ROOT`, `OUTPUT_DIR`, `CACHE_DIR`, `REPORTS_DIR`, plot dirs |
| `data_cache.py` | TTL network cache under `output/cache/` |
| `fetch_yahoo.py` | Cached Yahoo spot/history, BTC spot helpers |

## Data ingest

| File | Owns |
|------|------|
| `fetch_data.py` | Orchestrator: options, BTC history, yield curve, treasury legs, deltas |
| `fetch_asst_api.py` | ASST/SATA holdings → `treasury_extracted_data.json` |
| `fetch_share_dilution.py` | ASST+MSTR common overhang → `share_dilution.json`; patches rNAV share counts |
| `fetch_mstr_treasury.py` | strategy.com treasury/debt/shares → `mstr_*` JSON |
| `fetch_treasury_zero_yieldcurve.py` | FRED → Treasury zero curve |
| `ibit_option_deltas.py` | CRR tree Greeks enrichment |

## Valuation & capital structure

| File | Owns |
|------|------|
| `btc_price_paths.py` | Monte Carlo BTC path generation |
| `sata_valuation.py` | SATA dividend MC / NPV / sensitivities |
| `preferred_valuation.py` | Shared preferred MC helpers (SATA + STRC) |
| `strc_valuation.py` | STRC CLI wrapper over shared engine |
| `mstr_liquidation.py` | Senior claims, wipeout band, hedge amount |
| `mstr_nav.py` | MSTR **rNAV** (residual NAV/share after prefs + converts at market) |
| `asst_nav.py` | ASST **rNAV** (residual NAV/share after SATA at face/market + debt) |
| `mstr_hedge_helpers.py` | Theta / put sizing / book P&L for hedge notebook |
| `export_site_data.py` | `market_snapshot.json` + `fair_values.json` for `web/` |

## Presentation / utilities

| File | Owns |
|------|------|
| `html_report_generator.py` | Legacy self-contained HTML report |
| `check_baseline.py` | Optional sanity check for baseline in results JSON |
| `test_ibit_option_deltas_convexity.py` | Greeks / convexity tests |

## Notebooks (keep vs archive)

| Notebook | Role |
|----------|------|
| `mstr_options_hedge.ipynb` | Keep — STRC put hedge UX |
| `MSTR.ipynb` | Keep — EV/NAV worksheet |
| `ibit_options_hedge.ipynb` | Keep — SATA/IBIT hedge UX |
| `sata_playground.ipynb` | Sandbox; overlaps valuation sensitivities |
| `options_implied_distribution.ipynb` | Research-only |
| `archive/strc_valuation.ipynb` | Stale MC (old path format); superseded by `strc_valuation.py` |

## Anti-duplication rules

1. Debt principal / market value totals → only in `fetch_mstr_treasury.py` (+ `mstr_liquidation` for claims math).
2. Dividend path simulation → `preferred_valuation.py`, not copy-pasted notebooks.
3. Yahoo spots → `fetch_yahoo.py`.
4. Site never scrapes; it only reads exported JSON.
