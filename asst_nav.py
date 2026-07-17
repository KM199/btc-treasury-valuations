"""ASST residual NAV (rNAV) — common equity after SATA + debt.

  rNAV (face)   = BTC×spot + cash − SATA at $100 par − debt
  rNAV (market) = BTC×spot + cash − SATA at market − debt

  rNAV / share = rNAV / ASST diluted common shares

Denominator (from fetch_share_dilution / strategytracker):
  effective diluted = basic + RSUs/options (+ ITM warrants only).
  SATA preferred and debt are claims in the numerator — never diluted here.
  OTM warrants appear in gross diluted only, not the rNAV share count.
"""

from __future__ import annotations

from typing import Any

SATA_PAR = 100.0


def compute_asst_rnav(
    treasury: dict[str, Any],
    *,
    btc_price: float,
    asst_price: float | None = None,
    sata_price: float | None = None,
) -> dict[str, Any]:
    btc_holdings = float(treasury.get("btc_holdings") or 0)
    cash = float(treasury.get("cash") or 0)
    debt = float(treasury.get("debt") or 0)

    sata_shares = float(treasury.get("sata_shares") or 0)
    if sata_shares <= 0 and treasury.get("sata_notional"):
        sata_shares = float(treasury["sata_notional"]) / SATA_PAR

    sata_px = float(
        sata_price
        if sata_price is not None
        else treasury.get("sata_price") or 0
    )
    sata_face = sata_shares * SATA_PAR
    sata_market = sata_shares * sata_px if sata_px > 0 else sata_face

    btc_value = btc_holdings * float(btc_price)
    rnav_face = btc_value + cash - sata_face - debt
    rnav_market = btc_value + cash - sata_market - debt

    # ASST share count: prefer explicit diluted common from share_dilution fetch
    asst_shares = float(
        treasury.get("asst_shares")
        or treasury.get("asst_shares_diluted_effective")
        or 0
    )
    asst_px = float(asst_price) if asst_price is not None else 0.0
    mcap = float(treasury.get("mcap") or 0)
    if asst_shares <= 0 and mcap > 0 and asst_px > 0:
        asst_shares = mcap / asst_px
    if asst_shares <= 0 and mcap > 0 and asst_px <= 0:
        # leave shares unknown
        asst_shares = 0.0

    if asst_px <= 0 and mcap > 0 and asst_shares > 0:
        asst_px = mcap / asst_shares

    asst_mcap = asst_shares * asst_px if asst_shares > 0 and asst_px > 0 else mcap

    rnav_face_ps = rnav_face / asst_shares if asst_shares > 0 else None
    rnav_market_ps = rnav_market / asst_shares if asst_shares > 0 else None

    mnav_face = (
        (asst_mcap + sata_face + debt - cash) / btc_value if btc_value > 0 else None
    )
    mnav_market = (
        (asst_mcap + sata_market + debt - cash) / btc_value if btc_value > 0 else None
    )

    premium_face = None
    premium_market = None
    if asst_px > 0 and rnav_face_ps:
        premium_face = ((asst_px - rnav_face_ps) / rnav_face_ps) * 100.0
    if asst_px > 0 and rnav_market_ps:
        premium_market = ((asst_px - rnav_market_ps) / rnav_market_ps) * 100.0

    return {
        "btc_holdings": btc_holdings,
        "btc_price": float(btc_price),
        "btc_value": btc_value,
        "cash": cash,
        "debt": debt,
        "sata_shares": sata_shares,
        "sata_face": sata_face,
        "sata_market": sata_market,
        "sata_price": sata_px if sata_px > 0 else None,
        "asst_shares": asst_shares,
        "asst_price": asst_px if asst_px > 0 else None,
        "asst_market_cap": asst_mcap,
        "rnav_face_total": rnav_face,
        "rnav_market_total": rnav_market,
        "rnav_face_per_share": rnav_face_ps,
        "rnav_market_per_share": rnav_market_ps,
        "mnav_face": mnav_face,
        "mnav_market": mnav_market,
        "premium_face_pct": premium_face,
        "premium_market_pct": premium_market,
        # aliases for market-default fair value
        "rnav_total": rnav_market,
        "rnav_per_share": rnav_market_ps,
        "fair_value_per_share": rnav_market_ps,
    }
