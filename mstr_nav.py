"""MSTR residual NAV (rNAV) — fair value to common after stack adjustments.

Two rNAV variants (STRE always at euro face — no reliable live mark):

  rNAV (face)   = BTC×spot + cash − preferreds at par − converts at face
  rNAV (market) = BTC×spot + cash − preferreds at market − converts at market
                  (STRE still at face*)

  rNAV / share = rNAV / MSTR shares outstanding

mNAV total here means Bitcoin NAV = BTC holdings × spot (gross treasury mark).
"""

from __future__ import annotations

from typing import Any

PREFERRED_MARKET_SERIES = ("strc", "strd", "strk", "strf")
PREFERRED_PAR_USD = 100.0
STRE_PAR_EUR = 100.0


def _fx_rate(enriched: dict[str, Any]) -> float:
    fx = float(enriched.get("stre_fx_rate") or 0)
    if fx > 0:
        return fx
    eur = enriched.get("stre_price_eur")
    usd = enriched.get("stre_price")
    if eur and usd and float(eur) > 0:
        return float(usd) / float(eur)
    return 1.10


def preferred_market_caps(enriched: dict[str, Any]) -> dict[str, float]:
    """Market caps for liquid preferreds only (excludes STRE)."""
    caps: dict[str, float] = {}
    for series in PREFERRED_MARKET_SERIES:
        shares = float(enriched.get(f"{series}_shares") or 0)
        price = float(enriched.get(f"{series}_price") or 0)
        if shares > 0 and price > 0:
            caps[series] = shares * price
    return caps


def preferred_face_caps(enriched: dict[str, Any]) -> dict[str, float]:
    """Par / face for liquid preferreds ($100 stated amount)."""
    caps: dict[str, float] = {}
    for series in PREFERRED_MARKET_SERIES:
        shares = float(enriched.get(f"{series}_shares") or 0)
        if shares > 0:
            caps[series] = shares * PREFERRED_PAR_USD
    return caps


def stre_face_usd(enriched: dict[str, Any]) -> float:
    """STRE claim at euro par × FX (not a reliable market mark)."""
    shares = float(enriched.get("stre_shares") or 0)
    if shares <= 0:
        return 0.0
    return shares * STRE_PAR_EUR * _fx_rate(enriched)


def compute_mstr_rnav(
    enriched: dict[str, Any],
    *,
    btc_price: float | None = None,
    mstr_price: float | None = None,
    debt_at_market: bool = True,
) -> dict[str, Any]:
    """Compute Bitcoin NAV + rNAV at face and at market (per share too)."""
    btc_holdings = float(enriched.get("bitcoin_holdings") or 0)
    cash = float(enriched.get("cash") or 0)
    shares = float(enriched.get("mstr_shares") or 0)

    px_btc = float(btc_price if btc_price is not None else enriched.get("btc_price") or 0)
    px_mstr = float(mstr_price if mstr_price is not None else enriched.get("mstr_price") or 0)

    btc_value = btc_holdings * px_btc
    pref_mkt_caps = preferred_market_caps(enriched)
    pref_face_caps = preferred_face_caps(enriched)
    pref_market = float(sum(pref_mkt_caps.values()))
    pref_face = float(sum(pref_face_caps.values()))
    stre_face = stre_face_usd(enriched)
    stre_shares = float(enriched.get("stre_shares") or 0)

    debt_face = float(enriched.get("total_convertible_debt_principal") or 0)
    debt_mtm = float(
        enriched.get("total_convertible_debt_market_value")
        if enriched.get("total_convertible_debt_market_value") is not None
        else debt_face
    )

    prefs_face_total = pref_face + stre_face
    prefs_market_total = pref_market + stre_face  # STRE still face*

    rnav_face = btc_value + cash - prefs_face_total - debt_face
    rnav_market = btc_value + cash - prefs_market_total - debt_mtm

    rnav_face_ps = rnav_face / shares if shares > 0 else 0.0
    rnav_market_ps = rnav_market / shares if shares > 0 else 0.0

    # Backward-compatible aliases: default "rNAV" = market variant
    rnav = rnav_market if debt_at_market else rnav_face
    rnav_ps = rnav_market_ps if debt_at_market else rnav_face_ps

    mstr_mcap = shares * px_mstr if shares > 0 and px_mstr > 0 else 0.0
    enterprise_value = mstr_mcap + prefs_market_total + debt_mtm - cash
    mnav_multiple = enterprise_value / btc_value if btc_value > 0 else None

    return {
        "label": "rNAV",
        "description": (
            "rNAV face: prefs at par + debt at face. "
            "rNAV market: prefs at market + debt at market. STRE always face*."
        ),
        "btc_holdings": btc_holdings,
        "btc_price": px_btc,
        "btc_value": btc_value,
        "mnav_total": btc_value,
        "cash": cash,
        "preferred_market_cap": pref_market,
        "preferred_face_cap": pref_face,
        "preferred_by_series": pref_mkt_caps,
        "preferred_face_by_series": pref_face_caps,
        "preferreds_face_total_usd": prefs_face_total,
        "preferreds_market_total_usd": prefs_market_total,
        "stre_face_usd": stre_face,
        "stre_shares": stre_shares,
        "stre_pricing_note": (
            "STRE trades on LuxSE with thin quotes and no reliable Yahoo feed; "
            "both rNAV variants carry STRE at €100 par × FX."
        ),
        "convertible_debt": debt_mtm if debt_at_market else debt_face,
        "convertible_debt_face": debt_face,
        "convertible_debt_market": debt_mtm,
        "debt_at_market": debt_at_market,
        "mstr_market_cap": mstr_mcap,
        "mstr_market_price": px_mstr,
        "enterprise_value": enterprise_value,
        "mnav_multiple": mnav_multiple,
        "rnav_face_total": rnav_face,
        "rnav_market_total": rnav_market,
        "rnav_face_per_share": rnav_face_ps,
        "rnav_market_per_share": rnav_market_ps,
        # aliases (market variant)
        "rnav_total": rnav,
        "rnav_per_share": rnav_ps,
        "fair_value_per_share": rnav_ps,
        "premium_to_rnav_pct": (
            ((px_mstr - rnav_ps) / rnav_ps * 100.0) if rnav_ps else None
        ),
        "mstr_shares": shares,
    }
