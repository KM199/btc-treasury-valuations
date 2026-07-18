"""STRC liquidation waterfall: senior claims (debt + STRF market value) before STRC.

Wipeout band (seniority-adjusted liquidation math only):
- **Starts** at ``btc_price_strc_par`` — BTC where STRC liquidation/share = par ($100).
- **Ends** at ``btc_price_strc_zero`` — BTC where STRC liquidation/share = $0.

Full-stack BTC wipeouts: ``mstr_wipeout_ladder`` / ``asst_wipeout_ladder``.

Put hedge sizing: ``hedge_amount = strc_price − cash_covered_dividends``, where
cash-covered dividends = strategy.com **USD months of dividend coverage**
(USD reserve ÷ sum of stated preferred coupons) × monthly STRC coupon (not hedged).

**MSTR** common equity is junior to preferreds — wipeout anchor for the MSTR put leg is
**$0** (not BTC-proportional). Listed strikes are filtered near
``hedge_amount × (MSTR / STRC)`` in price space.
"""

from __future__ import annotations

from typing import Any

STRC_PAR_VALUE = 100.0
PREFERRED_DIVIDEND_SERIES = ("strc", "strd", "stre", "strf", "strk")


def total_preferred_annual_dividends_usd_from_tracker(tracker: dict) -> float:
    """Sum stated preferred coupons from strategy.com btcTrackerData."""
    total = 0.0
    for series in PREFERRED_DIVIDEND_SERIES:
        metrics = tracker.get(f"{series}_metrics") or {}
        shares = metrics.get("shares")
        dividend_pct = metrics.get("dividend")
        if shares is None or dividend_pct is None:
            continue
        total += float(shares) * STRC_PAR_VALUE * (float(dividend_pct) / 100.0)
    return total


def usd_months_dividend_coverage_from_cash(cash_usd: float, pref_annual_usd: float) -> float:
    """USD Months of Dividend Coverage on strategy.com."""
    if pref_annual_usd <= 0:
        return 0.0
    return cash_usd / (pref_annual_usd / 12.0)


def strf_market_value_usd(treas: dict) -> float:
    """Senior STRF claim at current market price (not par)."""
    return treas["strf_shares"] * treas["strf_price"]


def convertible_debt_claim_usd(treas: dict, *, at_market: bool = True) -> float:
    """Convertible claim: market value by default, face/notional if ``at_market=False``."""
    if at_market:
        mtm = treas.get("convertible_debt_market_value")
        if mtm is not None:
            return float(mtm)
    return float(treas.get("convertible_debt_principal") or 0)


def senior_claims_usd(treas: dict, *, debt_at_market: bool = True) -> float:
    """Senior claims ahead of STRC: converts (MTM by default) + STRF at market."""
    return convertible_debt_claim_usd(treas, at_market=debt_at_market) + strf_market_value_usd(treas)


def strc_liquidation_pool_usd(btc_price: float, treas: dict) -> float:
    assets = treas["btc_holdings"] * btc_price + treas["usd_reserve_usd"]
    return max(0.0, assets - senior_claims_usd(treas))


def strc_liquidation_per_share(btc_price: float, treas: dict) -> float:
    pool = strc_liquidation_pool_usd(btc_price, treas)
    return pool / treas["strc_shares"] if treas["strc_shares"] else 0.0


def strc_annual_dividend_per_share(treas: dict) -> float:
    eff = treas.get("strc_effective_yield")
    if eff is not None and float(eff) > 0:
        return float(eff) * STRC_PAR_VALUE
    return float(treas.get("strc_dividend_rate", 0) or 0) * STRC_PAR_VALUE


def strc_monthly_dividend_per_share(treas: dict) -> float:
    return strc_annual_dividend_per_share(treas) / 12.0


def usd_months_dividend_coverage(treas: dict) -> float:
    """USD Months of Dividend Coverage on strategy.com (cash ÷ monthly stated preferred coupons)."""
    cash = float(treas.get("usd_reserve_usd", 0) or 0)
    pref_annual = float(treas.get("total_preferred_annual_dividends_usd", 0) or 0)
    if pref_annual <= 0:
        raise KeyError(
            "total_preferred_annual_dividends_usd missing from treasury JSON — run fetch_mstr_treasury.py"
        )
    return usd_months_dividend_coverage_from_cash(cash, pref_annual)


def strc_cash_covered_dividend_per_share(treas: dict) -> float:
    """STRC dividends not hedged: website months of coverage × STRC monthly coupon."""
    return usd_months_dividend_coverage(treas) * strc_monthly_dividend_per_share(treas)


def strc_hedge_amount(treas: dict) -> float:
    """Hedge only STRC price minus cash-reserve-covered dividends."""
    return max(0.0, treas["strc_price"] - strc_cash_covered_dividend_per_share(treas))


def mstr_hedge_reference_strike(mstr_spot: float, treas: dict) -> float:
    """MSTR put strike near STRC hedge_amount (wipeout anchor for common = $0)."""
    strc = treas["strc_price"]
    if strc <= 0:
        return float("nan")
    return strc_hedge_amount(treas) * mstr_spot / strc


def btc_price_strc_par(
    treas: dict, par: float = STRC_PAR_VALUE, *, debt_at_market: bool = False
) -> float | None:
    """BTC where seniority-adjusted STRC liquidation/share hits par (wipeout band starts)."""
    need_assets = par * treas["strc_shares"] + senior_claims_usd(
        treas, debt_at_market=debt_at_market
    )
    need_btc = need_assets - treas["usd_reserve_usd"]
    if need_btc <= 0:
        return 0.0
    if not treas["btc_holdings"]:
        return None
    return need_btc / treas["btc_holdings"]


def btc_price_strc_zero(treas: dict, *, debt_at_market: bool = False) -> float | None:
    """BTC where seniority-adjusted STRC liquidation/share hits $0 (wipeout band ends)."""
    need = (
        senior_claims_usd(treas, debt_at_market=debt_at_market)
        - treas["usd_reserve_usd"]
    )
    if need <= 0:
        return 0.0
    if not treas["btc_holdings"]:
        return None
    return need / treas["btc_holdings"]


def _btc_for_asset_need(
    *,
    asset_need_usd: float,
    cash: float,
    btc_holdings: float,
) -> float | None:
    """BTC spot such that holdings×BTC + cash = asset_need_usd.

    Returns None when cash alone already meets the need (BTC cannot wipe further
    to that asset level), or holdings are missing.
    """
    if btc_holdings <= 0:
        return None
    need_from_btc = asset_need_usd - cash
    if need_from_btc <= 0:
        return None
    return need_from_btc / btc_holdings


def compute_wipeout_ladder(
    layers: list[dict[str, Any]],
    *,
    btc_holdings: float,
    cash: float,
    btc_spot: float,
) -> dict[str, Any]:
    """BTC levels where each claim is fully covered vs fully wiped.

    Seniority is the order of ``layers`` (index 0 = most senior).

    For layer i with claim C and seniors S:
      - btc_full  — assets = S + C  (this layer still whole)
      - btc_zero  — assets = S      (this layer wiped to $0)

    Common / residual layers should pass claim_usd=0; then btc_full is None and
    btc_zero is when seniors alone consume all assets.
    """
    rows: list[dict[str, Any]] = []
    senior = 0.0
    for layer in layers:
        name = str(layer.get("name") or "")
        claim = float(layer.get("claim_usd") or 0)
        kind = str(layer.get("kind") or "claim")
        note = layer.get("note")
        residual = bool(layer.get("residual")) or kind == "common"

        if residual:
            btc_full = None
            btc_zero = _btc_for_asset_need(
                asset_need_usd=senior, cash=cash, btc_holdings=btc_holdings
            )
        else:
            btc_full = _btc_for_asset_need(
                asset_need_usd=senior + claim,
                cash=cash,
                btc_holdings=btc_holdings,
            )
            btc_zero = _btc_for_asset_need(
                asset_need_usd=senior, cash=cash, btc_holdings=btc_holdings
            )

        row: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "claim_usd": claim if not residual else None,
            "senior_claims_usd": senior,
            "btc_full": btc_full,
            "btc_zero": btc_zero,
            "buffer_to_zero_pct": (
                ((btc_zero - btc_spot) / btc_spot) * 100.0
                if btc_zero is not None and btc_spot > 0
                else None
            ),
            "buffer_to_full_pct": (
                ((btc_full - btc_spot) / btc_spot) * 100.0
                if btc_full is not None and btc_spot > 0
                else None
            ),
        }
        if note:
            row["note"] = note
        rows.append(row)
        if not residual:
            senior += claim

    return {
        "btc_spot": btc_spot,
        "btc_holdings": btc_holdings,
        "cash": cash,
        "total_claims_usd": senior,
        "layers": rows,
    }


def mstr_wipeout_ladder(
    enriched: dict[str, Any],
    *,
    btc_price: float | None = None,
    debt_at_market: bool = False,
    preferreds_at_market: bool = False,
) -> dict[str, Any]:
    """Full Strategy stack wipeouts: debt → STRF → C → STRE → K → D → common.

    All claims default to **face** (bankruptcy / contractual). STRE = €100×FX.
    """
    from mstr_nav import preferred_face_caps, preferred_market_caps, stre_face_usd

    btc_holdings = float(
        enriched.get("bitcoin_holdings") or enriched.get("btc_holdings") or 0
    )
    cash = float(enriched.get("cash") or enriched.get("usd_reserve_usd") or 0)
    px_btc = float(
        btc_price
        if btc_price is not None
        else enriched.get("btc_price") or 0
    )

    debt = convertible_debt_claim_usd(
        {
            "convertible_debt_market_value": enriched.get(
                "total_convertible_debt_market_value"
            )
            or enriched.get("convertible_debt_market_value"),
            "convertible_debt_principal": enriched.get(
                "total_convertible_debt_principal"
            )
            or enriched.get("convertible_debt_principal"),
        },
        at_market=debt_at_market,
    )

    if preferreds_at_market:
        caps = preferred_market_caps(enriched)
    else:
        caps = preferred_face_caps(enriched)
    stre = stre_face_usd(enriched)

    # Seniority: converts → STRF → STRC → STRE (face*) → STRK → STRD → common
    layers = [
        {
            "name": "Convertible debt",
            "kind": "debt",
            "claim_usd": debt,
        },
        {
            "name": "STRF",
            "kind": "preferred",
            "claim_usd": float(caps.get("strf") or 0),
        },
        {
            "name": "STRC",
            "kind": "preferred",
            "claim_usd": float(caps.get("strc") or 0),
        },
        {
            "name": "STRE",
            "kind": "preferred",
            "claim_usd": stre,
        },
        {
            "name": "STRK",
            "kind": "preferred",
            "claim_usd": float(caps.get("strk") or 0),
        },
        {
            "name": "STRD",
            "kind": "preferred",
            "claim_usd": float(caps.get("strd") or 0),
        },
        {"name": "MSTR common", "kind": "common", "residual": True},
    ]
    ladder = compute_wipeout_ladder(
        layers, btc_holdings=btc_holdings, cash=cash, btc_spot=px_btc
    )
    ladder["basis"] = {
        "debt": "face" if not debt_at_market else "market",
        "preferreds": "face" if not preferreds_at_market else "market",
        "stre": "face",
    }
    # STRC $100/share contractual band; STRF at same basis as ladder
    strf_px = (
        100.0
        if not preferreds_at_market
        else float(enriched.get("strf_price") or 0)
    )
    treas = {
        "btc_holdings": btc_holdings,
        "usd_reserve_usd": cash,
        "btc_price": px_btc,
        "strc_shares": float(enriched.get("strc_shares") or 0),
        "strf_shares": float(enriched.get("strf_shares") or 0),
        "strf_price": strf_px,
        "convertible_debt_market_value": enriched.get(
            "total_convertible_debt_market_value"
        )
        or enriched.get("convertible_debt_market_value"),
        "convertible_debt_principal": enriched.get(
            "total_convertible_debt_principal"
        )
        or enriched.get("convertible_debt_principal"),
    }
    ladder["strc_par_band"] = {
        "btc_par": btc_price_strc_par(treas, debt_at_market=debt_at_market),
        "btc_zero": btc_price_strc_zero(treas, debt_at_market=debt_at_market),
        "note": "Contractual STRC $100/share band; seniors = convert + STRF at face",
    }
    return ladder


def asst_wipeout_ladder(
    treasury: dict[str, Any],
    *,
    btc_price: float,
    sata_price: float | None = None,
    sata_at_market: bool = False,
) -> dict[str, Any]:
    """ASST stack: debt → SATA → common. Claims default to face."""
    btc_holdings = float(treasury.get("btc_holdings") or 0)
    cash = float(treasury.get("cash") or 0)
    debt = float(treasury.get("debt") or 0)
    sata_shares = float(treasury.get("sata_shares") or 0)
    if sata_shares <= 0 and treasury.get("sata_notional"):
        sata_shares = float(treasury["sata_notional"]) / 100.0
    sata_face = sata_shares * 100.0
    sata_px = float(
        sata_price if sata_price is not None else treasury.get("sata_price") or 0
    )
    sata_claim = (
        (sata_shares * sata_px if sata_px > 0 else sata_face)
        if sata_at_market
        else sata_face
    )

    layers = [
        {"name": "Debt", "kind": "debt", "claim_usd": debt},
        {"name": "SATA", "kind": "preferred", "claim_usd": sata_claim},
        {"name": "ASST common", "kind": "common", "residual": True},
    ]
    ladder = compute_wipeout_ladder(
        layers, btc_holdings=btc_holdings, cash=cash, btc_spot=float(btc_price)
    )
    ladder["basis"] = {
        "debt": "face",
        "preferreds": "market" if sata_at_market else "face",
        "sata_par": 100.0,
    }
    return ladder


def _underlying_at_btc_level(
    treas: dict, underlying_price: float, btc_level: float | None
) -> float | None:
    if btc_level is None:
        return None
    btc_now = treas["btc_price"]
    if btc_now <= 0:
        return None
    return underlying_price * (btc_level / btc_now)


def ibit_price_strc_par(treas: dict, ibit_price: float) -> float | None:
    """Implied IBIT price when BTC hits wipeout start (STRC = par)."""
    return _underlying_at_btc_level(treas, ibit_price, btc_price_strc_par(treas))


def ibit_price_strc_zero(treas: dict, ibit_price: float) -> float | None:
    """Implied IBIT price when BTC hits wipeout end (STRC = $0)."""
    return _underlying_at_btc_level(treas, ibit_price, btc_price_strc_zero(treas))
