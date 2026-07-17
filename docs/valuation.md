# Valuation

How we turn Bitcoin price uncertainty into a **fair value per preferred share**.

## Big picture

1. Simulate thousands of monthly Bitcoin price paths over a long horizon (default: 100 years).
2. Along each path, apply the preferred’s dividend rules (pay from cash first; sell Bitcoin only when mark-to-market clears a suspension threshold).
3. Discount paid dividends to today → NPV per share.
4. Average across paths → **model fair value**. Compare to the **market price**.

## Dividend suspension (intuition)

Cash can always be used to pay dividends. Bitcoin sales are gated: if Bitcoin holdings marked to market fall below a multiple of par (the threshold), the company stops selling Bitcoin to fund dividends. Missed amounts can compound up to a cap.

Details live in `Configuration` and `simulate_dividend_path` inside the valuation modules.

## Analyses inside `sata_valuation.py`

| Analysis | Question |
|----------|----------|
| Baseline | Fair value at today’s BTC price |
| Multi-scenario | Same paths, different BTC starting prices (±10%) |
| Threshold sensitivity | How suspension multiplier changes NPV |
| Dividend-rate sensitivity | How coupon changes NPV |

## Paths file format

- `.npy` — uncompressed `N × T` price matrix (fast mmap)
- `.npz` — metadata / parameters

## Optimization

`--optimization-level 2` (default) early-exits insolvent paths to cut runtime.

## STRC

STRC uses the same engine via `preferred_valuation.py` / `strc_valuation.py`, with issuer parameters (par, dividend policy, shares, holdings) taken from MSTR treasury extracts.
