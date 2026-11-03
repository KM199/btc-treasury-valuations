# Data sources

| Source | Used for | Module |
|--------|----------|--------|
| Yahoo Finance | Equity/preferred spots, option chains, BTC history fallback | `fetch_yahoo.py`, `fetch_data.py` |
| strategy.com | MSTR convert debt, STRE/LuxSE, CMS share counts (when reachable; CI gets Akamai 403) | `fetch_mstr_treasury.py` |
| strategytracker | ASST treasury + dilution; **MSTR holdings/cash/preferreds** when strategy.com 403s. Ignore tracker `latestDebt` (often 0) and polluted preferred `sharesOutstanding`. | `fetch_asst_api.py`, `fetch_mstr_treasury.py`, `fetch_share_dilution.py` |
| FRED (DGS) | Treasury yields → zero curve for option Greeks / discounting | `fetch_treasury_zero_yieldcurve.py` |
| Cboe delayed quotes (`cdn.cboe.com/api/global/delayed_quotes/options/<T>.json`) | STRC chain with a synchronous underlying quote, when Yahoo 429s the options endpoint. Cboe's own `iv` field does not reprice its mids — solve IV yourself | `strc_call_writer.py` |
| Nasdaq (`api.nasdaq.com/api/quote/<T>/…`) | Option-chain fallback; **declared** STRC ex/record/pay dates and amounts; daily price history. Needs a browser-like User-Agent | `strc_call_writer.py` |

## Dividend yield for option Greeks

`ibit_option_deltas.py` solves implied vol on a CRR tree whose forward is `S·e^(r−q)T`, so
**q is a continuous yield on spot, never a coupon on par**. STRC pays a fixed *cash* 12% of
the **$100 stated amount** ($1.00/month) whatever the stock trades at, so at $98.67 spot the
right q is `12.00 / 98.67 = 12.16%` — not the stated 12%.

| Ticker | q | Why |
|--------|---|-----|
| STRC (and STRD/STRE/STRF/STRK/SATA) | `<t>_dividend_rate × $100 par / live spot`, else `<t>_effective_yield` | `output/mstr_treasury_extracted_data.json`, kept alive by strategytracker when strategy.com 403s |
| IBIT | 0 | Spot-BTC ETF, no distributions |
| MSTR | 0 | Common stock, no dividend |

`<t>_effective_yield` is the same current yield, but computed at the scraper's own staler
price (12.00/98.5455 = 12.177% vs 12.00/98.67 = 12.162%) — so it is the fallback, not the
primary. Compounding refinements are immaterial here: treating the monthly stream as
continuous (`−12·ln(1 − D/12S)` = 12.22%) moves solved IV by ≤0.10 vol points, and the
annual convention (`ln(1 + D/S)` = 11.48%) is simply wrong for a monthly payer.

**Never let a missing yield become 0.** Pricing STRC's puts at q = 0 overstated implied vol
by **4–9 vol points** (e.g. Mar-2027 $95 put: 27.3% against a true 18.5%) and corrupted every
Δ/Γ/ρ solved off that vol. `resolve_dividend_yield()` therefore classifies each ticker and
raises `MissingDividendYieldError` for a payer it cannot resolve; the chain is left
unenriched rather than written with wrong Greeks, and every enriched JSON records a
`dividend_yield_source` so consumers can audit it. Covered by
`test_dividend_yield_policy.py`.

## STRC dividend calendar (from Nov 2026)

STRC pays a dividend for **every calendar day** (8-K, 15 Oct 2026: 12.00%, $0.03/$0.04 a day,
$1.00 for November), each payable the next business day. With T+1 settlement the ex-date for a
record date is the first trading day whose settlement lands after it, so Saturday/Sunday record
dates go ex on Friday (~$0.10), Veterans Day (NYSE open, no settlement) goes ex the day before,
and the Friday of monthly option expiry is itself an ex-date. That is why the continuous-q CRR
tree above is fine for IV/Greeks but `strc_call_writer.py` prices early exercise on the
actual ladder.

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
