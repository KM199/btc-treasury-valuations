# Data sources

| Source | Used for | Module |
|--------|----------|--------|
| Yahoo Finance | Equity/preferred spots, option chains, BTC history fallback | `fetch_yahoo.py`, `fetch_data.py` |
| strategy.com | MSTR convert debt, STRE/LuxSE, CMS share counts (when reachable; CI gets Akamai 403) | `fetch_mstr_treasury.py` |
| strategytracker | ASST treasury + dilution; **MSTR holdings/cash/preferreds** when strategy.com 403s. Ignore tracker `latestDebt` (often 0) and polluted preferred `sharesOutstanding`. | `fetch_asst_api.py`, `fetch_mstr_treasury.py`, `fetch_share_dilution.py` |
| FRED (DGS) | Treasury yields → zero curve for option Greeks / discounting | `fetch_treasury_zero_yieldcurve.py` |

## Share dilution (rNAV denominator)

Preferreds and convertible debt are **claims** in the rNAV numerator — do **not** also dilute for them.

| Issuer | rNAV share count | Source |
| Issuer | rNAV share count | Source / policy |
|--------|------------------|-----------------|
| **ASST** | `latestEffectiveDilutedShares` (basic + RSUs/options; OTM warrants excluded) | strategytracker → `output/share_dilution.json` |
| **MSTR** | basic + options + RSU/PSU | strategy.com/shares. Converts stay as **debt**; STRK as **preferred** (no assumed conversion). Strategy’s assumed-diluted headline ignored. |

```bash
python fetch_share_dilution.py              # both
python fetch_share_dilution.py --asst-only
python fetch_share_dilution.py --force-refresh
```

Also runs at the end of a full `fetch_data.py` (when ASST/MSTR treasury legs run).

Yahoo `impliedSharesOutstanding` is dual-class consolidation, **not** warrant/option overhang — do not use it for dilution.

ASST SEC XBRL history is unreliable across the Feb-2026 reverse split; prefer strategytracker’s typed dilution table (cross-checked to 10-Q warrant/option footnotes).

## Freshness

- Network responses cached ~**1 hour** under `output/cache/` (`data_cache.py`). Use `--force-refresh` to bypass.
- Website **market** snapshot: CI ~**15 minutes**.
- Website **fair values**: CI **daily** (Monte Carlo is expensive).

Always show `as_of` / `timestamp` fields from JSON on the site — never imply tick-by-tick live prices.

## Fragility

Scrapers depend on `__NEXT_DATA__` / API shapes. strategy.com itself has **not** renamed `btcTrackerData`; Python/CI gets Akamai 403 HTML instead of that JSON. Holdings then come from strategytracker (`MSTR.v{version}.json`); convert debt stays on the last CMS scrape. When strategytracker changes markup, fetch scripts should fail loudly — fix parsers rather than hard-coding stale numbers.
