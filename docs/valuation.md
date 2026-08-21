# Valuation

How we turn Bitcoin price uncertainty into a **fair value per preferred share**.

## Big picture

1. Simulate thousands of monthly Bitcoin price paths over a long horizon (default: 100 years).
2. Along each path, apply the preferred’s dividend rules (pay from cash first; sell Bitcoin only when mark-to-market clears a suspension threshold).
3. Discount paid dividends to today → NPV per share.
4. Average across paths → **model fair value**. Compare to the **market price**.

## Dividend suspension (intuition)

Each month the model pays arrears first, then the current coupon, in this order:

1. **Cash, always.** The reserve is drawn down to zero before anything else. Cash is never gated by the suspension threshold.
2. **Then Bitcoin, but only if it clears the gate.** Once cash is exhausted, the shortfall is funded by selling Bitcoin — but only while Bitcoin marked to market is at least `threshold_multiplier ×` the net claim.
3. **Otherwise the dividend is suspended.** No Bitcoin is sold, the month goes unpaid, and the unpaid balance accumulates and compounds monthly until it can be paid in full — then the whole arrears balance is paid and the counter resets.

The compounding follows the certificate of designation: the first missed month accrues at the regular dividend rate **+ 25 bps**, and each further month unpaid adds another 25 bps, capped at **20% p.a.** (`compounded_dividend_start_rate` defaults to the live coupon; the loop adds the first 25 bps itself.)

### The net claim

The gate is measured against what the preferred actually costs, not its stated amount:

```
net claim = SATA shares × SATA market price − STRC shares held × STRC market price
```

SATA has traded persistently below its $100 stated amount, so par overstates the claim. And Strive holds Strategy's STRC preferred as a treasury asset — 505,000 shares as of the 10-Q for the quarter ended 2026-06-30 — which nets the claim down dollar for dollar. STRC is **not** added to the cash reserve: it is Bitcoin-correlated preferred paper that would be sold into the same stress that closes the gate, so it reduces what Bitcoin has to cover without ever paying a coupon itself.

Share count is a quarterly balance-sheet fact and is pinned in `preferred_valuation.STRC_SHARES_HELD`; the price is live, so the position is re-marked every run.

Dividends themselves are always computed on **gross par** (`shares × $100 × rate`) — netting affects only the Bitcoin-sale gate, never the obligation.

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

## Not modeled yet: issuance growth and the rate reset

Two of the biggest levers in this structure are frozen in the engine. `sata_shares_outstanding` and `sata_annual_dividend_rate` are both read once at setup, `sata_monthly_dividend_total` is hoisted out of the simulation loop as a constant, and Bitcoin holdings only ever go **down** — sold to fund dividends. No path issues a share, buys a coin, or changes the coupon. The dividend-rate sensitivity sweep is a static ±1pt comparison across separate runs, not a rate that moves along a path.

### Quantity: issuance scales with Bitcoin

When Bitcoin rises, the issuer sells more preferred to buy more Bitcoin. The two halves of that trade have different lifespans:

- **The new coupon is permanent and unconditional.** Every share issued raises `sata_monthly_dividend_total` for the remaining life of the structure.
- **The new Bitcoin is not.** It is bought at the rally price and can hand all of it back. Coverage was measured at the high; the obligation survives the round trip.
- **The gate base ratchets up with it.** `coverage_claim_value` scales with shares outstanding, so after the rally the Bitcoin mark has to clear a bar that grew during it.

The trigger is the issuer's appetite to add Bitcoin, not the preferred's own price — SATA is rate-pegged, so it does not rally with Bitcoin and there is no "trading above par" window that opens and closes. Strive has in fact bounded issuance by price: since March 2026 it has said it does not intend to issue SATA below $100.

### Rate: the peg is defended by raising the coupon

This is the larger omission. SATA is a variable-rate perpetual whose price is held near stated amount by resetting the coupon, not by appreciating. Per the [424B5 prospectus](https://www.sec.gov/Archives/edgar/data/1920406/000114036125040095/ny20056805x4_424b5.htm), Strive's stated intention is to adjust the monthly rate to keep the trading price inside a long-term band — originally $95–$105, and if the price is below the floor, "our current intention would be to increase the monthly regular dividend rate per annum." On [March 11, 2026](https://www.sec.gov/Archives/edgar/data/1920406/000162828026016664/asst-20260311.htm) that band was narrowed to **$99–$101**.

So the defence mechanism against a falling preferred price is a **higher coupon**, and the reset applies to the entire outstanding stack, not just newly issued shares. That is reflexive in the wrong direction: under peg → raise the rate → more cash out the door every month → coverage deteriorates → further under peg. The model, which holds 13.00% flat for the full horizon, never traverses that loop. It is countercyclical — the coupon rises precisely in the states where Bitcoin is least able to fund it — which makes it a worse omission than the issuance channel, not a smaller one.

### The reset is discretionary, and July 2026 proved it

The policy has an escape hatch written into it. The same prospectus paragraph ends: Strive will act "at our sole discretion based on our subjective assessment of market conditions." Elsewhere it warns it may adjust the rate "for any reason," including reasons unrelated to Bitcoin, credit spreads, or rates.

That hatch was used. SATA traded below its own $99 floor for the whole of July 2026, and the board did not raise:

| Decision (8-K) | SATA close that day | Band | Action |
|---|---|---|---|
| [Jun 15, 2026](https://www.sec.gov/Archives/edgar/data/1920406/000162828026016664/asst-20260311.htm) | $100.01 | in band | held 13.00% |
| **[Jul 14, 2026](https://www.sec.gov/Archives/edgar/data/0001920406/000162828026048231/asst-20260714.htm)** | **$97.92** | **below $99** | **held 13.00%** |
| [Aug 13, 2026](https://www.sec.gov/Archives/edgar/data/0001920406/000162828026056908/asst-20260813.htm) | $99.70 | in band | held 13.00% |

The July decision came after a genuine break: SATA closed at $83.53 on June 25 and traded as low as $79.01 intraday on June 26 — far below even the original $95 trigger — then spent all of July recovering between $95.40 and $98.76 without a single close at or above $99. The stated policy pointed at an increase. The board held.

**The 8-K gave no reason at all.** It is one sentence — the board "maintained the regular dividend rate per annum on the Company's SATA Stock at 13.00%" — with no rationale, no reference to the band, and no acknowledgement that the price was below it. The "market conditions" language is the standing discretion clause in the offering documents, not a July explanation. That the non-raise went entirely unexplained is the stronger fact.

For a holder this cuts both ways, and the model only sees one side:

- **Coverage-positive.** Not raising conserves cash and Bitcoin — exactly what the gate in this model cares about.
- **Peg-negative.** It also establishes that the band is defended only when convenient. It is an intention, revocable at sole discretion, and now demonstrably not binding. A holder cannot underwrite the $100 on the strength of the mechanism.

There is a live interaction worth checking here: the gate base is SATA marked **at market**, so a preferred trading down mechanically *shrinks* `coverage_claim_value` and makes Bitcoin sales easier to clear. The model therefore reads a broken peg as improved coverage. That is defensible — a cheaper claim genuinely is cheaper to stand behind — but it means price stress and gate stress move in opposite directions, and that should be a deliberate choice rather than a side effect.

### What it takes to model

Both the coupon and the share count have to become path variables recomputed inside the loop rather than hoisted out of it:

- An issuance rule keyed to the Bitcoin path, with proceeds converted to Bitcoin at that month's path price, and an issuance floor at $100 to match stated policy.
- A rate-reset rule keyed to the preferred's own simulated price — which means the model needs a price for SATA, not just a claim value, plus an explicit assumption about how reliably the issuer defends the band. July 2026 argues for a probabilistic or lagged defence rather than a hard rule: policy said raise, and the board did not.
- `sata_monthly_dividend_total` and `coverage_claim_value` recomputed monthly from both.
- Per-share NPV divided by a path-dependent share count rather than today's.

Rate history for calibration: 12.25% → 12.75% (Mar 11, 2026) → 13.00% ([Apr 15, 2026](https://www.sec.gov/Archives/edgar/data/0001920406/000162828026025154/strive-sataincreasebtcbuyu.htm)), then held at 13.00% for the July, August and September 2026 periods.

Common-equity dilution is tracked separately in `fetch_share_dilution.py` for the rNAV denominator — it is not fed back into this engine either.
