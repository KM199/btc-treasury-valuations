# Architecture

## Pipeline (SATA fair value)

```text
fetch_data.py
  → Yahoo: MSTR / STRC / IBIT chains + spots
  → BTC history, yield curve
  → fetch_asst_api.py      → treasury_extracted_data.json
  → fetch_mstr_treasury.py → mstr_* JSON
  → ibit_option_deltas.py  → enriched option Greeks

btc_price_paths.py
  → btc_price_paths_scenarios_price_paths.npy (~1GB)
  → btc_price_paths_scenarios_metadata.npz

sata_valuation.py
  → sata_valuation_results.json + output/plots/*.png

export_site_data.py
  → web/public/data/market_snapshot.json
  → web/public/data/fair_values.json

html_report_generator.py   # legacy HTML under reports/
```

## Run order (commands)

```bash
# Full SATA path
python fetch_data.py
python btc_price_paths.py
python sata_valuation.py
python export_site_data.py

# Light market refresh (website prices / treasury)
python fetch_data.py --skip-deltas
python export_site_data.py --market-only

# MSTR / STRC hedge only
python fetch_data.py --skip-asst
```

Useful `fetch_data.py` flags: `--only mstr|strc|ibit`, `--skip-asst`, `--skip-mstr-treasury`, `--skip-deltas`, `--force-refresh`.

## Auto-update cadence (CI)

| Job | Cadence | What runs |
|-----|---------|-----------|
| Light | ~15 minutes | fetch (skip deltas) + `export_site_data.py --market-only` |
| Heavy | Daily | paths if stale + `sata_valuation.py` + full `export_site_data.py` |

Deploy: GitHub Actions → commit/upload `web/public/data/*.json` → Vercel rebuild.

## Path layout

Centralized in [`strc_paths.py`](../strc_paths.py):

- `output/` — JSON, `.npy`/`.npz`, cache
- `output/plots/` — PNG charts (`matrix/`, `perf/` subfolders)
- `reports/` — legacy HTML
- `web/public/data/` — site-facing JSON

## Two products, one fetch spine

Do not invent parallel fetchers for the website. Site data is a thin export from the same `fetch_*` + valuation artifacts.
