# STRF Investment Thesis

## Overview

STRF is a fixed-rate perpetual preferred stock issued by Strategy (formerly MicroStrategy). It pays a **10% annual dividend** and sits at the **top of the preferred capital stack** — senior to STRC, STRD, STRE, and STRK. This seniority, combined with the company's ongoing convertible debt paydown, creates the conditions for meaningful capital appreciation on top of the 10% income stream.

---

## The Thesis

### 1. Income: 10% Fixed, Senior Claim

STRF's 10% coupon is fixed and sits above all other preferred series in liquidation priority. In a stress scenario, STRF holders get paid before STRC, STRD, STRE, and STRK holders — making it the most bond-like instrument in the preferred stack. The effective yield on a par-or-below purchase locks in a high nominal return with relatively strong structural protection.

### 2. Catalyst: Convertible Debt Paydown → Credit Quality Improvement

Strategy has six convertible notes outstanding that are senior to all preferred equity. As these are retired — via cash redemption, equity conversion, or refinancing — the senior claim ahead of STRF shrinks, improving its recovery value and compressing its required spread.

**Convertible debt schedule (data as of June 30, 2026):**

| Issue | Notional | Coupon | Maturity | Put Date | Strike |
|-------|----------|--------|----------|----------|--------|
| Convert 2028 | $1.010B | 0.625% | Sep 16, 2028 | Sep 16, 2027 | $183.19 |
| Convert 2029 | $1.500B | 0.000% | Dec 2, 2029 | Jun 2, 2028 | $672.40 |
| Convert 2030 B | $2.000B | 0.000% | Mar 2, 2030 | Mar 2, 2028 | $433.43 |
| Convert 2030 A | $0.800B | 0.625% | Mar 16, 2030 | Sep 16, 2028 | $149.77 |
| Convert 2031 | $0.604B | 0.875% | Mar 16, 2031 | Sep 16, 2028 | $232.72 |
| Convert 2032 | $0.800B | 2.250% | Jun 16, 2032 | Jun 16, 2029 | $204.33 |
| **Total** | **$6.714B** | | | | |

*Note: The 2029 notes were originally a $3B issuance. Strategy repurchased $1.5B of them in the open market at ~92 cents on the dollar (May 2026), saving ~$120M. The $1.5B shown above is what remains outstanding.*

**How put dates work:** A put date is an option *held by the bondholder* to force Strategy to repurchase the bonds at par (100 cents on the dollar) on that specific date. It is not a company-controlled event. Separately, Strategy can always go into the open market and buy back bonds at whatever price they trade — which is how they retired the $1.5B of 2029 notes below par. The put date sets a hard deadline: by that date, Strategy must be ready to pay par for any bonds whose holders elect to put them back.

**Contractual timeline (base case):**
- End of 2028: $1.01B cleared (Convert 2028 matures; put exercisable Sep 2027)
- End of 2030: $5.31B cleared (Converts 2029, 2030A, 2030B also gone)
- End of 2031: $5.91B cleared
- End of 2032: $6.71B cleared — full stack retired

**The timeline could be materially shorter.** Strategy has already demonstrated willingness to buy bonds back in the open market before put or maturity dates when they trade below par — and they achieve accretive savings when they do. If credit markets improve and Strategy's cost of capital falls, they could accelerate buybacks on the remaining issues. Every dollar retired early removes senior overhang above STRF ahead of schedule, pulling the credit improvement forward. The contractual dates above are the ceiling, not the expectation.

**Key nuances:**
- **All converts are out of the money at current MSTR prices (~$87).** Every strike ($149.77–$672.40) is well above where MSTR trades today. None will convert to shares unless MSTR recovers significantly, so the full remaining $6.71B will need cash, refinancing, or open-market repurchase to retire.
- **Put dates cluster in 2028.** Three issues totaling $4.30B have put dates in 2028 — Strategy must have liquidity ready well before those maturities.

### 3. Capital Appreciation Potential

If the market prices STRF at a spread appropriate for a senior preferred with minimal debt ahead of it, the price per share can move significantly. The math is straightforward: a fixed 10% coupon re-priced from, say, a 12% required yield to a 9% required yield represents roughly a 30% increase in price relative to par. The magnitude of appreciation depends on where spreads are at entry and how far they compress as debt is retired.

---

## Key Risk: BTC Price Exposure

The underlying credit quality of all Strategy preferreds is ultimately tied to the value of the Bitcoin treasury. A sharp BTC drawdown could offset the credit improvement from debt paydown.

**Wipeout levels (as of June 30, 2026):**
- BTC holdings: 845,256 BTC
- Total convertible debt (senior to STRF): $6.71B
- STRF wipeout BTC price: **~$7,943** (where BTC collateral value = senior debt)
- STRF wipeout IBIT price: **~$3.04** (IBIT currently $33.29)

**Hedge structure: deep OTM IBIT puts ($3–5 strike)**

IBIT puts at the $3–5 strike are the aligned hedge — they correspond to $13K–$7,900 BTC, which is the range where STRF actually starts getting impaired. This is 85–90% out of the money, meaning the IV skew is steep and pricing is expensive, but the payoff alignment is real. A $30 IBIT put ($78K BTC) would be misaligned — STRF is fine there.

**Known gap: intermediate basis risk.** If BTC falls 50% from here (~$43K BTC / ~$16 IBIT), STRF takes a significant price hit from credit spread widening, but the $3–5 puts are still out of the money and not paying off. This mismatch in the intermediate range is accepted as a structural limitation of the hedge. The puts are sized to cover the terminal scenario, not the intermediate drawdown.

**Net carry:** 10.67% yield minus put cost (TBD on strike, expiry, and fill). Intermediate basis risk is managed through position sizing rather than hedging.

---

## Summary

| Element | Description |
|---------|-------------|
| Instrument | STRF fixed preferred, 10% coupon |
| Seniority | Most senior preferred (above STRC, STRD, STRE, STRK) |
| Income | 10% annual dividend on par value |
| Catalyst | Convertible debt paydown → credit quality improvement → spread compression |
| Timeline | Contractually defined by convertible maturity schedule |
| Key risk | BTC price decline offsetting credit improvement |
| Wipeout level | ~$7,943 BTC / ~$3.04 IBIT (845,256 BTC holdings vs. $6.71B senior debt) |
| Hedge | Deep OTM IBIT puts, $3–5 strike — aligned to actual wipeout, not intermediate drawdown |
