# Capital structure

## Strategy (MSTR) stack (simplified)

Senior → junior:

1. **Convertible debt** (market value)
2. **STRF** preferred
3. **STRC** preferred
4. **STRE** preferred (euro face*)
5. **STRK** preferred
6. **STRD** preferred
7. **MSTR** common

BTC wipeout ladder: `mstr_wipeout_ladder` / `asst_wipeout_ladder` in [`mstr_liquidation.py`](../mstr_liquidation.py) — exported on the site capital-structure page.

## Debt: market value vs face

[strategy.com/debt](https://www.strategy.com/debt) lists each convert’s **notional** and **market value** (from last traded price × face).

| Use | Basis |
|-----|--------|
| Default senior claims / NAV-style views | **Market value** of converts + STRF at market |
| Stress / contractual claim at par | Face / notional (available as footnote / toggle) |

We scrape `convertData` in `fetch_mstr_treasury.py` and persist:

- `total_convertible_debt_principal` (face)
- `total_convertible_debt_market_value` (MTM)
- per-issue `last_traded_price`, `market_value` (computed or CMS)

`mstr_liquidation.senior_claims_usd` defaults to **market value** for converts.

## MSTR rNAV (fair value to common)

rNAV (not Strategy’s headline **mNAV** multiple). Our site fair value for MSTR is **rNAV / share**:

```text
rNAV = BTC × spot + cash
     − liquid preferreds at market (STRC, STRD, STRK, STRF)
     − STRE at face* (€100 par × FX)
     − converts at market
rNAV/share = rNAV / MSTR shares
```

\*STRE has no reliable live Yahoo/Nasdaq mark (LuxSE). See [`mstr_nav.py`](../mstr_nav.py).

Implemented in [`mstr_nav.py`](../mstr_nav.py); same residual stack as `MSTR.ipynb`, with debt marked to market by default.

## ASST rNAV (fair value to common)

Strive (ASST) stack is simpler: Bitcoin + cash, then **SATA** preferred, then common.

```text
rNAV (face)   = BTC × spot + cash − SATA at $100 par − debt
rNAV (market) = BTC × spot + cash − SATA at market − debt
rNAV/share    = rNAV / ASST shares
```

ASST share count is **effective diluted common** from strategytracker (basic + RSUs/options; OTM warrants excluded). SATA stays a preferred claim — never diluted into the share count. See [`fetch_share_dilution.py`](../fetch_share_dilution.py) and [`asst_nav.py`](../asst_nav.py).

## Wipeout band (STRC)

Seniority-adjusted liquidation math:

- Band **starts** where STRC liquidation/share ≈ par ($100)
- Band **ends** where STRC liquidation/share ≈ $0

See `mstr_liquidation.py`. Hedge sizing hedges price risk net of cash-covered dividends (strategy.com months of coverage).

## ASST / SATA

Separate issuer. Holdings, cash, and SATA shares come from strategytracker via `fetch_asst_api.py` → `treasury_extracted_data.json`.
