# Bitcoin Treasury Valuations

Monte Carlo valuation and capital-structure analysis for Bitcoin treasury companies and their preferred stock — currently focused on **SATA** (ASST) and **STRC** / **MSTR** (Strategy).

This repo is both a research pipeline and the data backend for a portfolio web app under [`web/`](web/).

**Human docs:** see [`docs/`](docs/) for overview, architecture, modules, valuation math, capital structure, and data sources.  
**Agent ops notes:** [`CLAUDE.md`](CLAUDE.md).

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Use a **single** env at `venv/` (do not create a parallel `.venv/`).

### SATA fair-value pipeline

```bash
python fetch_data.py
python btc_price_paths.py
python sata_valuation.py
# Legacy HTML (optional; site is the primary UI):
python html_report_generator.py
```

### MSTR / STRC market + hedge

```bash
python fetch_data.py --skip-asst
# Then open MSTR.ipynb or mstr_options_hedge.ipynb
```

### Website (local)

```bash
python export_site_data.py          # writes web/public/data/*.json
cd web && npm install && npm run dev
```

Artifacts land in `output/` (JSON, paths, plots) and `reports/` (legacy HTML). Paths are centralized in [`strc_paths.py`](strc_paths.py).

## What this is not

- Not investment advice.
- Not a real-time tick feed — market snapshots refresh on a schedule (~15 minutes in CI); Monte Carlo fair values refresh daily.
