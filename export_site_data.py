#!/usr/bin/env python3
"""Export site-facing JSON under web/public/data/ from output/ artifacts.

Market prices always prefer live Yahoo spots (not stale treasury scrapes).

Usage:
  python export_site_data.py              # market + fair values
  python export_site_data.py --market-only
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asst_nav import compute_asst_rnav
from fetch_yahoo import load_btc_spot, yahoo_spot_price
from mstr_liquidation import (
    asst_wipeout_ladder,
    ibit_price_strc_par,
    ibit_price_strc_zero,
    mstr_hedge_reference_strike,
    mstr_wipeout_ladder,
    strc_cash_covered_dividend_per_share,
    strc_hedge_amount,
    strc_monthly_dividend_per_share,
    usd_months_dividend_coverage,
)
from mstr_hedge_helpers import IBIT_HEDGE_SPREADS
from mstr_nav import compute_mstr_rnav
from hedge_story import build_hedge_story
from preferred_story import build_preferred_story, load_btc_path_fan_from_output
from strc_paths import OUTPUT_DIR, PROJECT_ROOT, ensure_output_dirs

SITE_DATA_DIR = PROJECT_ROOT / "web" / "public" / "data"

TICKERS = ("MSTR", "STRC", "ASST", "SATA")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _price_from_ticker_json(path: Path) -> float | None:
    data = _load_json(path)
    if not data:
        return None
    for key in ("current_price", "price", "regularMarketPrice"):
        if data.get(key) is not None:
            try:
                return float(data[key])
            except (TypeError, ValueError):
                pass
    return None


def _live_spot(symbol: str, *, force_refresh: bool = True) -> float | None:
    """Yahoo first; never silently trust multi-week-old treasury fields."""
    return yahoo_spot_price(symbol, force_refresh=force_refresh)


def build_market_snapshot(
    output_dir: Path = OUTPUT_DIR,
    *,
    force_refresh: bool = True,
) -> dict[str, Any]:
    """Assemble market + treasury snapshot; equity/preferred prices from Yahoo."""
    asst = _load_json(output_dir / "treasury_extracted_data.json") or {}
    mstr_enriched = _load_json(output_dir / "mstr_enriched_data.json") or {}
    mstr_hedge = _load_json(output_dir / "mstr_treasury_extracted_data.json") or {}

    btc_price = load_btc_spot(output_dir, force_refresh=force_refresh, log=False)
    # Prefer Yahoo BTC over stale historical JSON when refreshing for the site
    y_btc = _live_spot("BTC-USD", force_refresh=force_refresh)
    if y_btc is not None:
        btc_price = y_btc

    prices: dict[str, float | None] = {}
    for t in TICKERS:
        live = _live_spot(t, force_refresh=force_refresh)
        if live is not None:
            prices[t] = live
            continue
        # Fallbacks only if Yahoo fails
        if t == "MSTR":
            prices[t] = (
                float(mstr_enriched.get("mstr_price") or 0)
                or _price_from_ticker_json(output_dir / "mstr_data.json")
            )
        elif t == "STRC":
            prices[t] = (
                float(mstr_enriched.get("strc_price") or mstr_hedge.get("strc_price") or 0)
                or _price_from_ticker_json(output_dir / "strc_data.json")
            )
        elif t == "ASST":
            prices[t] = _price_from_ticker_json(output_dir / "asst_data.json")
        elif t == "SATA":
            # Stale treasury sata_price is last resort only
            fallback = asst.get("sata_price")
            prices[t] = float(fallback) if fallback is not None else None

    debt_face = float(
        mstr_hedge.get("convertible_debt_principal")
        or mstr_enriched.get("total_convertible_debt_principal")
        or 0
    )
    debt_mtm = float(
        mstr_hedge.get("convertible_debt_market_value")
        or mstr_enriched.get("total_convertible_debt_market_value")
        or debt_face
    )
    strf_mv = float(mstr_hedge.get("strf_market_value") or 0)
    if not strf_mv:
        strf_mv = float(mstr_hedge.get("strf_shares") or 0) * float(
            mstr_hedge.get("strf_price") or mstr_enriched.get("strf_price") or 0
        )

    senior_claims_mtm = debt_mtm + strf_mv
    senior_claims_face = debt_face + strf_mv

    # Live preferred prices into enriched copy for rNAV / wipeouts
    enriched_for_nav = dict(mstr_enriched)
    if prices.get("STRC") is not None:
        enriched_for_nav["strc_price"] = prices["STRC"]
    if prices.get("MSTR") is not None:
        enriched_for_nav["mstr_price"] = prices["MSTR"]
    # Prefer hedge JSON debt totals when enriched is stale
    if debt_mtm:
        enriched_for_nav["total_convertible_debt_market_value"] = debt_mtm
    if debt_face:
        enriched_for_nav["total_convertible_debt_principal"] = debt_face
    if mstr_hedge.get("strf_shares"):
        enriched_for_nav["strf_shares"] = mstr_hedge["strf_shares"]
    if mstr_hedge.get("strf_price"):
        enriched_for_nav["strf_price"] = mstr_hedge["strf_price"]
    if mstr_hedge.get("btc_holdings"):
        enriched_for_nav["bitcoin_holdings"] = mstr_hedge["btc_holdings"]
    if mstr_hedge.get("usd_reserve_usd"):
        enriched_for_nav["cash"] = mstr_hedge["usd_reserve_usd"]

    rnav = compute_mstr_rnav(
        enriched_for_nav,
        btc_price=btc_price,
        mstr_price=prices.get("MSTR"),
        debt_at_market=True,
    )

    asst_rnav = compute_asst_rnav(
        asst,
        btc_price=btc_price,
        asst_price=prices.get("ASST"),
        sata_price=prices.get("SATA"),
    )

    mstr_wipeouts = mstr_wipeout_ladder(
        enriched_for_nav,
        btc_price=btc_price,
        debt_at_market=False,
        preferreds_at_market=False,
    )
    asst_wipeouts = asst_wipeout_ladder(
        asst, btc_price=btc_price, sata_at_market=False
    )

    # STRC hedge strip (deterministic; uses live STRC price when available)
    strc_px = float(prices.get("STRC") or mstr_hedge.get("strc_price") or 0)
    hedge_treas = {
        **mstr_hedge,
        "strc_price": strc_px,
        "btc_price": btc_price,
        "btc_holdings": float(
            mstr_hedge.get("btc_holdings")
            or mstr_enriched.get("bitcoin_holdings")
            or 0
        ),
        "usd_reserve_usd": float(
            mstr_hedge.get("usd_reserve_usd") or mstr_enriched.get("cash") or 0
        ),
        "strc_shares": float(mstr_hedge.get("strc_shares") or 0),
    }
    strc_hedge: dict[str, Any] | None = None
    try:
        if strc_px > 0 and hedge_treas.get("strc_shares"):
            covered = strc_cash_covered_dividend_per_share(hedge_treas)
            months_cov = usd_months_dividend_coverage(hedge_treas)
            hedge_amt = strc_hedge_amount(hedge_treas)
            monthly = strc_monthly_dividend_per_share(hedge_treas)
            band = mstr_wipeouts.get("strc_par_band") or {}
            spot = float(btc_price or 0)
            btc_par = band.get("btc_par")
            btc_zero = band.get("btc_zero")
            mstr_px = float(prices.get("MSTR") or 0)
            try:
                ibit_px = float(yahoo_spot_price("IBIT") or 0)
            except Exception:
                ibit_px = 0.0
            strc_hedge = {
                "strc_price": strc_px,
                "monthly_dividend_per_share": monthly,
                "cash_covered_dividend_per_share": covered,
                "usd_months_dividend_coverage": months_cov,
                "hedge_amount_per_share": hedge_amt,
                "btc_spot": spot or None,
                "btc_par": btc_par,
                "btc_zero": btc_zero,
                "buffer_to_par_pct": (
                    ((btc_par - spot) / spot) * 100.0
                    if btc_par is not None and spot > 0
                    else None
                ),
                "buffer_to_zero_pct": (
                    ((btc_zero - spot) / spot) * 100.0
                    if btc_zero is not None and spot > 0
                    else None
                ),
                "seniors": "Converts + STRF",
                "mstr_price": mstr_px or None,
                "mstr_reference_strike": (
                    mstr_hedge_reference_strike(mstr_px, hedge_treas)
                    if mstr_px > 0
                    else None
                ),
                "ibit_price": ibit_px or None,
                "ibit_at_par": (
                    ibit_price_strc_par(hedge_treas, ibit_px)
                    if ibit_px > 0
                    else None
                ),
                "ibit_at_zero": (
                    ibit_price_strc_zero(hedge_treas, ibit_px)
                    if ibit_px > 0
                    else None
                ),
                "ibit_spreads": [
                    {"long": float(lo), "short": float(sh)}
                    for lo, sh in IBIT_HEDGE_SPREADS
                ],
            }
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        strc_hedge = None

    # SATA wipeout strip from ladder
    sata_hedge: dict[str, Any] | None = None
    try:
        layers = asst_wipeouts.get("layers") or []
        sata_layer = next(
            (L for L in layers if str(L.get("name") or "").upper() == "SATA"),
            None,
        )
        spot = float(btc_price or 0)
        if sata_layer:
            btc_full = sata_layer.get("btc_full")
            btc_zero = sata_layer.get("btc_zero")
            sata_hedge = {
                "sata_price": prices.get("SATA"),
                "claim_usd": sata_layer.get("claim_usd"),
                "btc_full": btc_full,
                "btc_zero": btc_zero,
                "buffer_to_full_pct": (
                    ((btc_full - spot) / spot) * 100.0
                    if btc_full is not None and spot > 0
                    else None
                ),
                "buffer_to_zero_pct": (
                    ((btc_zero - spot) / spot) * 100.0
                    if btc_zero is not None and spot > 0
                    else None
                ),
            }
    except (TypeError, ValueError, StopIteration):
        sata_hedge = None

    names = {
        "MSTR": ("Strategy common", "Strategy", "common"),
        "STRC": ("Stretch preferred", "Strategy", "preferred"),
        "ASST": ("Strive common", "ASST", "common"),
        "SATA": ("SATA preferred", "ASST", "preferred"),
    }
    instruments = []
    for t in TICKERS:
        name, issuer, kind = names[t]
        row: dict[str, Any] = {
            "ticker": t,
            "name": name,
            "issuer": issuer,
            "market_price": prices.get(t),
            "kind": kind,
            "price_source": "yahoo",
        }
        if kind == "preferred":
            row["par"] = 100.0
        if t == "MSTR" and rnav.get("rnav_per_share"):
            row["fair_value_hint"] = rnav["rnav_per_share"]
            row["fair_label"] = "rNAV"
        if t == "ASST" and asst_rnav.get("rnav_per_share"):
            row["fair_value_hint"] = asst_rnav["rnav_per_share"]
            row["fair_label"] = "rNAV"
        instruments.append(row)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "btc_price": btc_price,
        "btc": {
            "price": btc_price,
            "mstr_holdings": rnav.get("btc_holdings"),
            "mstr_btc_value": rnav.get("btc_value"),
            "asst_holdings": asst_rnav.get("btc_holdings") or asst.get("btc_holdings"),
            "asst_btc_value": asst_rnav.get("btc_value"),
        },
        "instruments": instruments,
        "mstr": {
            "btc_holdings": mstr_hedge.get("btc_holdings")
            or mstr_enriched.get("bitcoin_holdings"),
            "usd_reserve_usd": mstr_hedge.get("usd_reserve_usd") or mstr_enriched.get("cash"),
            "convertible_debt_principal": debt_face,
            "convertible_debt_market_value": debt_mtm,
            "strf_market_value": strf_mv,
            "senior_claims_market_usd": senior_claims_mtm,
            "senior_claims_face_usd": senior_claims_face,
            "strc_shares": mstr_hedge.get("strc_shares"),
            "source": mstr_hedge.get("source") or "https://www.strategy.com/",
            "rnav": rnav,
            "wipeouts": mstr_wipeouts,
            "strc_hedge": strc_hedge,
        },
        "asst": {
            "btc_holdings": asst.get("btc_holdings"),
            "cash": asst.get("cash"),
            "sata_shares": asst.get("sata_shares"),
            "sata_dividend_rate": asst.get("sata_dividend_rate"),
            "debt": asst.get("debt"),
            "mcap": asst.get("mcap"),
            "source": asst.get("source"),
            "rnav": asst_rnav,
            "wipeouts": asst_wipeouts,
            "sata_hedge": sata_hedge,
        },
        "notes": {
            "debt_valuation": (
                "Convertible debt senior claims default to market value "
                "(last traded price × notional), not face."
            ),
            "mstr_fair_value": (
                "MSTR model fair = rNAV/share (BTC + cash − liquid preferreds at market "
                "− STRE at face* − converts at market), not Strategy's mNAV multiple."
            ),
            "asst_fair_value": (
                "ASST model fair = rNAV/share (BTC + cash − SATA at market − debt). "
                "Face column marks SATA at $100 par."
            ),
            "stre": (
                "STRE has no reliable Nasdaq/Yahoo mark (LuxSE, thin). "
                "rNAV uses €100 par × FX face, shown separately with *."
            ),
            "freshness": (
                "Equity/preferred/BTC spots from Yahoo on each export; "
                "CI refreshes ~15 minutes. Browser also polls /api/quotes."
            ),
        },
    }


def build_fair_values(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    """Chart-friendly fair value payload from valuation results (+ optional STRC)."""
    sata = _load_json(output_dir / "sata_valuation_results.json")
    strc = _load_json(output_dir / "strc_valuation_results.json")
    market = build_market_snapshot(output_dir, force_refresh=True)
    price_by_ticker = {
        i["ticker"]: i.get("market_price") for i in market.get("instruments", [])
    }

    tickers: list[dict[str, Any]] = []

    def _entry(
        ticker: str,
        fair: float | None,
        *,
        source: str,
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mkt = price_by_ticker.get(ticker)
        gap = None
        gap_pct = None
        if fair is not None and mkt is not None and mkt != 0:
            gap = fair - float(mkt)
            gap_pct = (gap / float(mkt)) * 100.0
        row: dict[str, Any] = {
            "ticker": ticker,
            "market_price": mkt,
            "fair_value": fair,
            "gap": gap,
            "gap_pct": gap_pct,
            "source": source,
        }
        if extras:
            row.update(extras)
        return row

    if sata:
        base = sata.get("baseline_results") or {}
        fair = base.get("final_valuation_per_share") or base.get("mean_npv_per_share")
        meta = sata.get("metadata") or {}
        scenarios = _scenario_series(sata)
        tickers.append(
            _entry(
                "SATA",
                float(fair) if fair is not None else None,
                source="sata_valuation.py",
                extras={
                    "mean_months_paid": base.get("mean_months_paid"),
                    "median_months_paid": base.get("median_months_paid"),
                    "valuation_vs_par": base.get("valuation_vs_par"),
                    "valuation_as_of": meta.get("timestamp") or meta.get("generated_at"),
                    "scenarios": scenarios,
                    "npv_distribution": _npv_hist_friendly(sata),
                },
            )
        )

    if strc:
        base = strc.get("baseline_results") or {}
        fair = base.get("final_valuation_per_share") or base.get("mean_npv_per_share")
        meta = strc.get("metadata") or {}
        tickers.append(
            _entry(
                "STRC",
                float(fair) if fair is not None else None,
                source="strc_valuation.py",
                extras={
                    "mean_months_paid": base.get("mean_months_paid"),
                    "valuation_vs_par": base.get("valuation_vs_par"),
                    "valuation_as_of": meta.get("timestamp") or meta.get("generated_at"),
                    "scenarios": _scenario_series(strc),
                },
            )
        )
    else:
        tickers.append(
            _entry("STRC", None, source="pending", extras={"status": "model_pending"})
        )

    # MSTR fair = rNAV market / share
    rnav = (market.get("mstr") or {}).get("rnav") or {}
    mstr_fair = rnav.get("rnav_market_per_share") or rnav.get("rnav_per_share")
    tickers.append(
        _entry(
            "MSTR",
            float(mstr_fair) if mstr_fair is not None else None,
            source="mstr_nav.rNAV_market",
            extras={
                "fair_label": "rNAV mkt",
                "rnav_face_per_share": rnav.get("rnav_face_per_share"),
                "rnav_market_per_share": rnav.get("rnav_market_per_share"),
                "rnav_face_total": rnav.get("rnav_face_total"),
                "rnav_market_total": rnav.get("rnav_market_total"),
                "premium_to_rnav_pct": rnav.get("premium_to_rnav_pct"),
                "btc_value": rnav.get("btc_value"),
            },
        )
    )

    # ASST fair = rNAV market / share
    asst_rnav = (market.get("asst") or {}).get("rnav") or {}
    asst_fair = asst_rnav.get("rnav_market_per_share") or asst_rnav.get("rnav_per_share")
    tickers.append(
        _entry(
            "ASST",
            float(asst_fair) if asst_fair is not None else None,
            source="asst_nav.rNAV_market",
            extras={
                "fair_label": "rNAV mkt",
                "rnav_face_per_share": asst_rnav.get("rnav_face_per_share"),
                "rnav_market_per_share": asst_rnav.get("rnav_market_per_share"),
                "rnav_face_total": asst_rnav.get("rnav_face_total"),
                "rnav_market_total": asst_rnav.get("rnav_market_total"),
                "premium_face_pct": asst_rnav.get("premium_face_pct"),
                "premium_market_pct": asst_rnav.get("premium_market_pct"),
                "btc_value": asst_rnav.get("btc_value"),
            },
        )
    )

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "tickers": tickers,
        "comparison": [
            {
                "ticker": t["ticker"],
                "market": t.get("market_price"),
                "fair": t.get("fair_value"),
            }
            for t in tickers
            if t.get("fair_value") is not None
            or t["ticker"] in ("SATA", "STRC", "MSTR", "ASST")
        ],
        "mstr_rnav": rnav,
        "asst_rnav": asst_rnav,
    }


def _scenario_series(results: dict[str, Any]) -> list[dict[str, Any]]:
    from preferred_story import _scenario_enriched

    return _scenario_enriched(results)


def _npv_hist_friendly(results: dict[str, Any]) -> dict[str, Any] | None:
    base = results.get("baseline_results") or {}
    if not base:
        return None
    return {
        "mean": base.get("mean_npv_per_share"),
        "median": base.get("median_npv_per_share"),
        "std": base.get("std_npv_per_share"),
        "vs_par": base.get("valuation_vs_par"),
        "final_per_share": base.get("final_valuation_per_share"),
    }


def write_site_data(
    output_dir: Path = OUTPUT_DIR,
    site_dir: Path = SITE_DATA_DIR,
    *,
    market_only: bool = False,
    force_refresh: bool = True,
) -> None:
    ensure_output_dirs()
    site_dir.mkdir(parents=True, exist_ok=True)

    market = build_market_snapshot(output_dir, force_refresh=force_refresh)
    market_path = site_dir / "market_snapshot.json"
    with market_path.open("w") as f:
        json.dump(market, f, indent=2)
    print(f"  ✓ Wrote {market_path}")
    for inst in market["instruments"]:
        px = inst.get("market_price")
        print(f"    {inst['ticker']}: {px}")

    # Always ensure share_dilution.json has both issuers, then publish to site
    from fetch_share_dilution import build_share_dilution

    dilution_src = output_dir / "share_dilution.json"
    existing = _load_json(dilution_src) or {}
    if not existing.get("asst") or not existing.get("mstr"):
        build_share_dilution(output_dir, force_refresh=False)
        existing = _load_json(dilution_src) or {}
    if not existing.get("asst") or not existing.get("mstr"):
        raise RuntimeError(
            "share_dilution.json missing asst or mstr after refresh — "
            "check fetch_share_dilution.py / network."
        )
    dilution_dst = site_dir / "share_dilution.json"
    with dilution_dst.open("w") as f:
        json.dump(existing, f, indent=2)
        f.write("\n")
    print(f"  ✓ Wrote {dilution_dst}")

    if not market_only:
        fair = build_fair_values(output_dir)
        fair_path = site_dir / "fair_values.json"
        with fair_path.open("w") as f:
            json.dump(fair, f, indent=2)
        print(f"  ✓ Wrote {fair_path}")

        sata = _load_json(output_dir / "sata_valuation_results.json")
        strc = _load_json(output_dir / "strc_valuation_results.json")
        price_by = {
            i["ticker"]: i.get("market_price") for i in market.get("instruments", [])
        }
        story = build_preferred_story(
            sata_results=sata,
            strc_results=strc,
            sata_market=price_by.get("SATA"),
            strc_market=price_by.get("STRC"),
        )
        story["as_of"] = fair.get("as_of")
        story["hedge"] = build_hedge_story(output_dir=output_dir, market=market)
        path_fan = load_btc_path_fan_from_output(output_dir)
        if path_fan:
            story["path_fan"] = path_fan
            print(
                f"  ✓ Path fan: {path_fan['n_sample_paths']} samples × "
                f"{path_fan['months']} months"
            )
        else:
            story["path_fan"] = None
            print("  ⚠ Path fan skipped (btc_price_paths_scenarios_price_paths.npy missing)")
        story_path = site_dir / "preferred_story.json"
        with story_path.open("w") as f:
            json.dump(story, f, indent=2)
        print(f"  ✓ Wrote {story_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export JSON for the portfolio website")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--site-dir", type=Path, default=SITE_DATA_DIR)
    parser.add_argument(
        "--market-only",
        action="store_true",
        help="Only refresh market_snapshot.json (skip fair_values)",
    )
    parser.add_argument(
        "--no-force-refresh",
        action="store_true",
        help="Allow 1h Yahoo cache (default: force fresh spots)",
    )
    args = parser.parse_args()
    write_site_data(
        args.output_dir,
        args.site_dir,
        market_only=args.market_only,
        force_refresh=not args.no_force_refresh,
    )


if __name__ == "__main__":
    main()
