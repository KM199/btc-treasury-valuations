"""Build Preferreds-page hedge story from liquidation math + option notebooks.

STRC three-leg race: ``mstr_options_hedge.ipynb`` / ``mstr_hedge_helpers``.
SATA + IBIT long puts: ``ibit_options_hedge.ipynb``.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import mstr_hedge_helpers as hh
from fetch_treasury_zero_yieldcurve import TreasuryZeroCurve
from ibit_option_deltas import (
    DEFAULT_DIV_YIELD,
    DEFAULT_TREE_STEPS,
    american_price_crr,
    implied_vol_bisection,
    year_fraction_to_expiry,
)
from mstr_liquidation import (
    STRC_PAR_VALUE,
    ibit_price_strc_par,
    ibit_price_strc_zero,
    mstr_hedge_reference_strike,
    strc_cash_covered_dividend_per_share,
    strc_hedge_amount,
    strc_monthly_dividend_per_share,
    usd_months_dividend_coverage,
)
from strc_paths import OUTPUT_DIR


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _finite(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _row_records(df: pd.DataFrame, cols: list[str], *, limit: int = 12) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    use = [c for c in cols if c in df.columns]
    out: list[dict[str, Any]] = []
    for _, row in df.head(limit).iterrows():
        rec: dict[str, Any] = {}
        for c in use:
            v = row[c]
            if pd.isna(v):
                rec[c] = None
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                rec[c] = round(float(v), 4) if abs(float(v)) < 1e6 else float(v)
            else:
                rec[c] = v if isinstance(v, (str, int, float, bool)) else str(v)
        out.append(rec)
    return out


def _best_book_row(book: pd.DataFrame) -> dict[str, Any] | None:
    if book is None or book.empty or "total_yield" not in book.columns:
        return None
    best = book.loc[book["total_yield"].idxmax()]
    if pd.notna(best.get("short_strike")):
        label = best.get("spread") or f"{best['strike']:.0f}/{best['short_strike']:.0f}"
    else:
        label = best.get("strike")
    return {
        "strike_label": str(label),
        "strike": _finite(best.get("strike")),
        "short_strike": _finite(best.get("short_strike")),
        "mid_price": _finite(best.get("mid_price")),
        "contracts_needed": _finite(best.get("contracts_needed")),
        "num_shares": _finite(best.get("num_shares")),
        "dividend": _finite(best.get("dividend")),
        "borrow_cost": _finite(best.get("borrow_cost")),
        "theta_cost": _finite(best.get("theta_cost")),
        "tax_benefit": _finite(best.get("tax_benefit")),
        "hedge_cost_after_tax": _finite(best.get("hedge_cost_after_tax")),
        "total_yield": _finite(best.get("total_yield")),
    }


def _pnl_series(pnl: pd.DataFrame) -> list[dict[str, Any]]:
    """Collapse P&L sensitivity to average book P&L by shock (for a simple chart)."""
    if pnl is None or pnl.empty:
        return []
    shock_cols = [c for c in pnl.columns if isinstance(c, str) and c.endswith("%")]
    if not shock_cols:
        return []
    series = []
    for c in shock_cols:
        vals = pd.to_numeric(pnl[c], errors="coerce").dropna()
        if vals.empty:
            continue
        pct = int(c.replace("%", "").replace("+", ""))
        series.append({"shock_pct": pct, "pnl": round(float(vals.mean()), 2)})
    return sorted(series, key=lambda r: r["shock_pct"])


def _sata_put_shock_pnl(
    *,
    spot: float,
    strike: float,
    mid: float,
    option_contracts: float,
    expiration: str,
    ibit_data: dict[str, Any],
    output_dir: Path,
) -> list[dict[str, Any]]:
    """CRR put-book $ P&L under parallel spot/rate shocks when chain lacks Greeks."""
    if spot <= 0 or strike <= 0 or mid <= 0 or option_contracts <= 0:
        return []
    try:
        exp = date.fromisoformat(expiration)
    except ValueError:
        return []
    ts = ibit_data.get("timestamp")
    try:
        valuation = (
            datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if ts
            else datetime.now(timezone.utc)
        )
    except ValueError:
        valuation = datetime.now(timezone.utc)
    T = year_fraction_to_expiry(valuation, exp)
    if not math.isfinite(T) or T <= 0:
        return []

    r = 0.04
    curve_path = output_dir / "yield_curve.json"
    if curve_path.is_file():
        try:
            raw = json.loads(curve_path.read_text())
            curve = TreasuryZeroCurve.from_saved_dict(raw)
            r_eq = curve.equivalent_constant_rate(T)
            if math.isfinite(r_eq):
                r = float(r_eq)
        except Exception:
            pass

    sig = implied_vol_bisection(
        mid, spot, strike, T, r, DEFAULT_DIV_YIELD, n_steps=DEFAULT_TREE_STEPS, is_call=False
    )
    if sig is None or not math.isfinite(sig) or sig <= 0:
        return []

    V0 = american_price_crr(
        spot, strike, T, r, DEFAULT_DIV_YIELD, sig, n_steps=DEFAULT_TREE_STEPS, is_call=False
    )
    if not math.isfinite(V0):
        return []

    series = []
    for p in hh.SHOCK_PCTS_WIDE:
        h = p / 100.0
        S1 = spot * (1 + h)
        r1 = r * (1 + h)
        V1 = american_price_crr(
            S1, strike, T, r1, DEFAULT_DIV_YIELD, sig, n_steps=DEFAULT_TREE_STEPS, is_call=False
        )
        if not math.isfinite(V1):
            continue
        pnl = option_contracts * hh.CONTRACT_MULT * (V1 - V0)
        series.append(
            {
                "shock_pct": int(p),
                "option_pnl": round(float(pnl), 2),
                "pnl": round(float(pnl), 2),
            }
        )
    return series


def _scenario_fair_points(
    scenarios: list[dict[str, Any]],
    zero_btc_fair: float | None = None,
) -> list[tuple[float, float]]:
    """(shock %, model fair) points from the MC scenario curve, sorted by shock.

    `zero_btc_fair` adds the −100% end point: Bitcoin at zero is not a scenario
    the grid covers, but it is exactly computable — cash pays the coupon until it
    runs out — so it anchors the curve instead of being extrapolated into.
    """
    pts: list[tuple[float, float]] = []
    for r in scenarios:
        p = r.get("btc_start_pct")
        f = r.get("fair_value")
        if p is None or f is None:
            continue
        try:
            # stored as fraction (−0.5) or already percent (−50)
            pf = float(p)
            x = pf * 100.0 if abs(pf) <= 1.5 else pf
            pts.append((x, float(f)))
        except (TypeError, ValueError):
            continue
    if zero_btc_fair is not None and not any(x <= -100.0 for x, _ in pts):
        pts.append((-100.0, float(zero_btc_fair)))
    pts.sort(key=lambda t: t[0])
    return pts


def _interp_fair_at_shock(
    scenarios: list[dict[str, Any]],
    shock_pct: float,
    zero_btc_fair: float | None = None,
) -> tuple[float, bool] | None:
    """Model fair at a BTC start shock (−50 for −50%), plus whether it is extrapolated.

    The scenario grid stops at ±75%; the stress chart runs to ±100%. The −100%
    end is anchored by `zero_btc_fair` when it is known. Anywhere else outside
    the grid, extend the slope of the two outermost points (floored at zero)
    rather than holding the endpoint flat — a flat tail would say another 25%
    down costs SATA holders nothing.
    """
    pts = _scenario_fair_points(scenarios, zero_btc_fair)
    if len(pts) < 2:
        return None
    if shock_pct < pts[0][0]:
        (x0, y0), (x1, y1) = pts[0], pts[1]
    elif shock_pct > pts[-1][0]:
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
    else:
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= shock_pct <= x1:
                break
        else:
            return None
        if abs(x1 - x0) < 1e-12:
            return y0, False
        t = (shock_pct - x0) / (x1 - x0)
        return y0 + t * (y1 - y0), False
    if abs(x1 - x0) < 1e-12:
        return y0, True
    slope = (y1 - y0) / (x1 - x0)
    return max(0.0, y0 + slope * (shock_pct - x0)), True


def _enrich_pnl_with_preferred(
    pnl_series: list[dict[str, Any]],
    *,
    scenarios: list[dict[str, Any]],
    num_shares: float,
    zero_btc_fair: float | None = None,
) -> list[dict[str, Any]]:
    """Add SATA fair Δ (from MC scenario curve) and net book P&L next to option P&L."""
    if not pnl_series or not scenarios or not (num_shares > 0):
        return pnl_series
    base = _interp_fair_at_shock(scenarios, 0.0, zero_btc_fair)
    if base is None:
        return pnl_series
    fair0 = base[0]
    out = []
    for row in pnl_series:
        shock = float(row.get("shock_pct") or 0)
        option = float(row.get("option_pnl") if row.get("option_pnl") is not None else row.get("pnl") or 0)
        hit = _interp_fair_at_shock(scenarios, shock, zero_btc_fair)
        fair_s, extrapolated = hit if hit is not None else (None, False)
        preferred = (
            (fair_s - fair0) * num_shares if fair_s is not None else None
        )
        net = option + preferred if preferred is not None else option
        out.append(
            {
                **row,
                "option_pnl": round(option, 2),
                "preferred_pnl": round(preferred, 2) if preferred is not None else None,
                "preferred_fair": round(fair_s, 2) if fair_s is not None else None,
                "preferred_extrapolated": bool(extrapolated) if fair_s is not None else None,
                "pnl": round(net, 2),
                "net_pnl": round(net, 2),
            }
        )
    return out


def build_strc_three_leg(
    *,
    output_dir: Path,
    treas: dict[str, Any],
    strc_px: float,
    mstr_px: float,
    ibit_px: float,
    btc_spot: float,
) -> dict[str, Any] | None:
    strc_data = _load(output_dir / "strc_data.json")
    mstr_data = _load(output_dir / "mstr_data.json")
    ibit_data = _load(output_dir / "ibit_data.json")
    if not strc_data or not mstr_data or not ibit_data:
        return None

    strc_options = _load(output_dir / "strc_options.json") or {}
    mstr_options = _load(output_dir / "mstr_options.json") or {}
    ibit_options = _load(output_dir / "ibit_options.json") or {}

    hedge_treas = {
        **treas,
        "strc_price": strc_px,
        "btc_price": btc_spot,
    }
    wipe_ibit = ibit_price_strc_zero(hedge_treas, ibit_px) if ibit_px > 0 else None

    leg_specs = [
        ("STRC puts", strc_data, strc_options, float(strc_data.get("current_price") or strc_px), None),
        ("MSTR puts", mstr_data, mstr_options, float(mstr_data.get("current_price") or mstr_px), None),
        (
            "IBIT put spreads",
            ibit_data,
            ibit_options,
            float(ibit_data.get("current_price") or ibit_px),
            wipe_ibit,
        ),
    ]

    legs_out: list[dict[str, Any]] = []
    leg_results: list[dict[str, Any]] = []
    for name, data, options, spot, wipe in leg_specs:
        try:
            leg = hh.analyze_hedge_leg(
                name, data, options, hedge_treas, spot=spot, wipeout_price=wipe
            )
        except Exception as exc:  # noqa: BLE001 — export must not die on one thin chain
            legs_out.append({"leg": name, "error": str(exc)})
            continue
        leg_results.append(leg)
        book = leg.get("book")
        hedge_calc = leg.get("hedge_calc")
        best = _best_book_row(book)
        ladder_cols = [
            "strike",
            "short_strike",
            "spread",
            "mid_price",
            "coverage_gap",
            "contracts_needed",
            "annualized_theta_cost",
            "num_shares",
            "total_yield",
            "hedge_cost_after_tax",
        ]
        legs_out.append(
            {
                "leg": name,
                "structure": leg.get("hedge_structure"),
                "spot": _finite(leg.get("spot")),
                "last_expiration": leg.get("last_expiration"),
                "second_last_expiration": leg.get("second_last_expiration"),
                "wipeout_price": _finite(leg.get("wipeout_price")),
                "hedge_reference_strike": _finite(leg.get("hedge_reference_strike")),
                "optimal_strike": _finite(leg.get("optimal_strike")),
                "best": best,
                "ladder": _row_records(
                    book if book is not None and not book.empty else hedge_calc,
                    ladder_cols,
                    limit=10,
                ),
                "pnl_series": _pnl_series(leg.get("pnl")),
            }
        )

    cmp = hh.comparison_summary(leg_results) if leg_results else pd.DataFrame()
    comparison = []
    if not cmp.empty:
        for _, row in cmp.iterrows():
            comparison.append(
                {
                    "leg": row.get("Leg"),
                    "expirations": row.get("Expirations"),
                    "strikes": int(row["Strikes"]) if pd.notna(row.get("Strikes")) else 0,
                    "best_strike": (
                        None
                        if pd.isna(row.get("Best Strike"))
                        else row.get("Best Strike")
                    ),
                    "hedge_cost_10k": _finite(row.get("Hedge Cost ($10k)")),
                    "total_yield_10k": _finite(row.get("Total Yield ($10k)")),
                }
            )

    winner = None
    scored = [c for c in comparison if c.get("total_yield_10k") is not None]
    if scored:
        winner = max(scored, key=lambda r: r["total_yield_10k"])

    return {
        "capital": hh.CAPITAL,
        "margin_requirement": hh.STRC_MARGIN_REQUIREMENT,
        "cost_of_capital": hh.COST_OF_CAPITAL,
        "marginal_tax_rate": hh.MARGINAL_TAX_RATE,
        "ibit_spreads": [
            {"long": float(a), "short": float(b)} for a, b in hh.IBIT_HEDGE_SPREADS
        ],
        "comparison": comparison,
        "winner": winner,
        "legs": legs_out,
    }


def build_sata_ibit_hedge(
    *,
    output_dir: Path,
    asst: dict[str, Any],
    sata_px: float,
    scenarios: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    ibit_data = _load(output_dir / "ibit_data.json")
    if not ibit_data or not asst:
        return None

    cash = float(asst.get("cash") or 0)
    debt = float(asst.get("debt") or 0)
    notional = float(asst.get("sata_notional") or 0)
    btc_holdings = float(asst.get("btc_holdings") or 0)
    if sata_px <= 0 or notional <= 0:
        return None

    cash_cushion_per_share = (cash - debt) * 100.0 / notional
    hedge_amount = max(0.0, sata_px - cash_cushion_per_share)

    ibit_spot = float(ibit_data.get("current_price") or 0)
    btc_per = float(ibit_data.get("btc_per_share") or 0)
    assets = btc_holdings * ibit_spot / btc_per + cash if btc_per > 0 else None
    optimal = (
        ibit_spot * (debt + notional) / assets
        if assets and assets > 0 and ibit_spot > 0
        else None
    )

    assumptions = {
        "capital": float(hh.CAPITAL),
        "margin_requirement": 0.15,
        "margin_note": "15% Interactive Brokers-style margin on SATA (notebook Reg-T proxy)",
        "cost_of_capital": float(hh.COST_OF_CAPITAL),
        "marginal_tax_rate": float(hh.MARGINAL_TAX_RATE),
        "contract_multiplier": int(hh.CONTRACT_MULT),
    }

    base_out: dict[str, Any] = {
        "sata_price": sata_px,
        "hedge_amount_per_share": hedge_amount,
        "cash_cushion_per_share": cash_cushion_per_share,
        "ibit_spot": ibit_spot or None,
        "optimal_strike": optimal,
        "assumptions": assumptions,
        "capital": assumptions["capital"],
        "margin_requirement": assumptions["margin_requirement"],
    }

    chain = ibit_data.get("options_data") or _load(output_dir / "ibit_options.json") or {}
    expirations = ibit_data.get("expirations") or sorted(chain.keys())
    if len(expirations) < 2 or ibit_spot <= 0:
        return {
            **base_out,
            "note": "Need ≥2 IBIT expirations for theta ladder.",
            "ladder": [],
            "best": None,
            "near_optimal": None,
            "book": None,
            "pnl_series": [],
        }

    last, second = sorted(expirations)[-1], sorted(expirations)[-2]
    puts_last = hh.get_puts_below_price(last, ibit_spot, chain, 5.0)
    puts_second = hh.get_puts_below_price(second, ibit_spot, chain, 5.0)
    puts_last = puts_last[puts_last["strike"] % 5 == 0].copy()
    puts_second = puts_second[puts_second["strike"] % 5 == 0].copy()
    if puts_last.empty or puts_second.empty:
        return {
            **base_out,
            "last_expiration": last,
            "second_last_expiration": second,
            "ladder": [],
            "best": None,
            "near_optimal": None,
            "book": None,
            "pnl_series": [],
        }

    theta = hh.compute_theta_table(puts_last, puts_second, last, second)
    gcols = [
        c
        for c in ("delta", "gamma", "rho", "risk_free_rate", "implied_volatility")
        if c in puts_last.columns
    ]
    hedge_calc = puts_last[["strike", "mid_price", *gcols]].copy()
    hedge_calc["contracts_needed"] = hedge_amount / (
        hedge_calc["strike"] - hedge_calc["mid_price"]
    )
    hedge_calc = hedge_calc.merge(
        theta[["strike", "estimated_theta"]], on="strike", how="inner"
    )
    hedge_calc["annualized_theta_cost"] = (
        hedge_calc["estimated_theta"] * hedge_calc["contracts_needed"] * 365.25
    )
    hedge_calc["cost_of_hedge_options"] = (
        hedge_calc["contracts_needed"] * hedge_calc["mid_price"]
    )

    sata_yield = float(asst.get("sata_effective_yield") or 0)
    if sata_yield <= 0:
        rate = float(asst.get("sata_dividend_rate") or 0.13)
        if rate > 1:
            rate /= 100.0
        # Dollar dividend is rate on par ($100), not rate on the fluctuating market
        # price — matches strc_annual_dividend_per_share's par-based calculation.
        sata_yield = STRC_PAR_VALUE * rate

    capital = float(hh.CAPITAL)
    margin = 0.15
    coc = float(hh.COST_OF_CAPITAL)
    tax = float(hh.MARGINAL_TAX_RATE)
    hedge_calc["capital_per_share"] = (
        hedge_calc["mid_price"] * hedge_calc["contracts_needed"] + margin * sata_px
    )
    hedge_calc["num_shares"] = capital / hedge_calc["capital_per_share"]
    hedge_calc["option_contracts"] = (
        hedge_calc["num_shares"] * hedge_calc["contracts_needed"] / hh.CONTRACT_MULT
    )
    hedge_calc["dividend"] = hedge_calc["num_shares"] * sata_yield
    hedge_calc["total_purchase"] = hedge_calc["num_shares"] * (
        sata_px + hedge_calc["cost_of_hedge_options"]
    )
    hedge_calc["borrow_cost"] = -(hedge_calc["total_purchase"] - capital) * coc
    hedge_calc["theta_cost"] = (
        -hedge_calc["annualized_theta_cost"] * hedge_calc["num_shares"]
    )
    hedge_calc["tax_benefit"] = (-tax) * (
        hedge_calc["theta_cost"] + hedge_calc["borrow_cost"]
    )
    hedge_calc["total_yield_pre_tax"] = (
        hedge_calc["dividend"] + hedge_calc["theta_cost"] + hedge_calc["borrow_cost"]
    )
    hedge_calc["total_yield"] = (
        hedge_calc["total_yield_pre_tax"] + hedge_calc["tax_benefit"]
    )
    hedge_calc["hedge_cost_after_tax"] = -(
        hedge_calc["theta_cost"] + hedge_calc["borrow_cost"] + hedge_calc["tax_benefit"]
    )
    hedge_calc["return_pct"] = hedge_calc["total_yield"] / capital * 100.0
    hedge_calc["return_pct_pre_tax"] = (
        hedge_calc["total_yield_pre_tax"] / capital * 100.0
    )

    best = _best_book_row(hedge_calc)
    near_optimal = None
    book = None
    pnl_series: list[dict[str, Any]] = []
    scenario_grid_pct: float | None = None
    zero_btc: dict[str, Any] | None = None
    if optimal is not None and not hedge_calc.empty:
        hedge_calc = hedge_calc.copy()
        hedge_calc["dist"] = (hedge_calc["strike"] - optimal).abs()
        near_idx = hedge_calc["dist"].idxmin()
        near = hedge_calc.loc[near_idx]
        near_optimal = {
            "strike": _finite(near["strike"]),
            "mid_price": _finite(near["mid_price"]),
            "contracts_needed": _finite(near["contracts_needed"]),
            "option_contracts": _finite(near["option_contracts"]),
            "num_shares": _finite(near["num_shares"]),
            "capital_per_share": _finite(near["capital_per_share"]),
            "total_purchase": _finite(near["total_purchase"]),
            "dividend": _finite(near["dividend"]),
            "borrow_cost": _finite(near["borrow_cost"]),
            "theta_cost": _finite(near["theta_cost"]),
            "tax_benefit": _finite(near["tax_benefit"]),
            "total_yield_pre_tax": _finite(near["total_yield_pre_tax"]),
            "total_yield": _finite(near["total_yield"]),
            "hedge_cost_after_tax": _finite(near["hedge_cost_after_tax"]),
            "return_pct_pre_tax": _finite(near["return_pct_pre_tax"]),
            "return_pct": _finite(near["return_pct"]),
            "delta": _finite(near["delta"]) if "delta" in near.index else None,
            "implied_volatility": (
                _finite(near["implied_volatility"])
                if "implied_volatility" in near.index
                else None
            ),
        }
        book = near_optimal

        # Stress: option-book $ P&L under parallel IBIT shocks (notebook CRR / Greeks).
        near_frame = hedge_calc.loc[[near_idx]].copy()
        try:
            pnl = hh.compute_pnl_sensitivity(
                near_frame, ibit_spot, last, ibit_data,
                shock_pcts=hh.SHOCK_PCTS_WIDE,
            )
            pnl_series = _pnl_series(pnl)
            # Attach option_pnl alias for the chart.
            pnl_series = [
                {**r, "option_pnl": r.get("pnl")} for r in pnl_series
            ]
        except Exception:
            pnl_series = []
        if not pnl_series and near_optimal.get("option_contracts") and near_optimal.get("mid_price"):
            pnl_series = _sata_put_shock_pnl(
                spot=ibit_spot,
                strike=float(near_optimal["strike"]),
                mid=float(near_optimal["mid_price"]),
                option_contracts=float(near_optimal["option_contracts"]),
                expiration=last,
                ibit_data=ibit_data,
                output_dir=output_dir,
            )
            if pnl_series and near_optimal.get("implied_volatility") is None:
                # Store the IV used for stress so the UI can show it.
                try:
                    T = year_fraction_to_expiry(
                        datetime.now(timezone.utc), date.fromisoformat(last)
                    )
                    r = 0.04
                    sig = implied_vol_bisection(
                        float(near_optimal["mid_price"]),
                        ibit_spot,
                        float(near_optimal["strike"]),
                        T,
                        r,
                        DEFAULT_DIV_YIELD,
                        n_steps=DEFAULT_TREE_STEPS,
                        is_call=False,
                    )
                    if sig is not None:
                        near_optimal["implied_volatility"] = float(sig)
                        if book is not None:
                            book["implied_volatility"] = float(sig)
                except Exception:
                    pass

        # Combine option P&L with SATA fair move from the MC scenario curve.
        scen = scenarios
        if not scen:
            try:
                from preferred_story import _scenario_enriched

                raw_results = _load(output_dir / "sata_valuation_results.json")
                if raw_results:
                    scen = _scenario_enriched(raw_results)
            except Exception:
                scen = []
        if pnl_series and scen and near_optimal.get("num_shares"):
            # Bitcoin at zero is the one point past the grid we can compute
            # exactly (cash pays the coupon until it is gone), so anchor the
            # −100% end rather than extrapolating into it.
            try:
                from sata_valuation import zero_btc_fair_value_per_share

                zero_btc = zero_btc_fair_value_per_share(str(output_dir))
            except Exception:
                zero_btc = None
            zero_fair = zero_btc.get("fair_value") if zero_btc else None
            pnl_series = _enrich_pnl_with_preferred(
                pnl_series,
                scenarios=scen,
                num_shares=float(near_optimal["num_shares"]),
                zero_btc_fair=zero_fair,
            )
            grid = _scenario_fair_points(scen)
            if grid:
                scenario_grid_pct = min(abs(grid[0][0]), abs(grid[-1][0]))

    ladder = _row_records(
        hedge_calc.sort_values("strike"),
        [
            "strike",
            "mid_price",
            "contracts_needed",
            "option_contracts",
            "num_shares",
            "dividend",
            "theta_cost",
            "borrow_cost",
            "tax_benefit",
            "total_yield_pre_tax",
            "total_yield",
            "return_pct_pre_tax",
            "return_pct",
            "hedge_cost_after_tax",
        ],
        limit=16,
    )

    return {
        **base_out,
        "annual_dividend_per_share": sata_yield,
        "last_expiration": last,
        "second_last_expiration": second,
        "best": best,
        "near_optimal": near_optimal,
        "book": book,
        "pnl_series": pnl_series,
        "scenario_grid_pct": scenario_grid_pct,
        "zero_btc_fair": zero_btc,
        "ladder": ladder,
        "note": (
            "Wipeout-aligned IBIT put only (nearest listed to claims/assets × spot). "
            "Returns on $10k capital with 15% IB margin; tax benefit at marginal rate."
        ),
    }


def build_hedge_story(
    *,
    output_dir: Path | None = None,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full hedge payload for preferred_story.json / Preferreds page."""
    output_dir = Path(output_dir or OUTPUT_DIR)
    market = market or {}

    asst = _load(output_dir / "treasury_extracted_data.json") or {}
    mstr_hedge = _load(output_dir / "mstr_treasury_extracted_data.json") or {}
    mstr_enriched = _load(output_dir / "mstr_enriched_data.json") or {}
    ibit_data = _load(output_dir / "ibit_data.json") or {}

    prices = {
        i["ticker"]: i.get("market_price")
        for i in (market.get("instruments") or [])
        if isinstance(i, dict) and i.get("ticker")
    }
    strc_px = float(prices.get("STRC") or mstr_hedge.get("strc_price") or 0)
    mstr_px = float(prices.get("MSTR") or mstr_enriched.get("mstr_price") or 0)
    sata_px = float(prices.get("SATA") or asst.get("sata_price") or 0)
    btc_spot = float(
        market.get("btc_price")
        or ibit_data.get("btc_price")
        or mstr_enriched.get("btc_price")
        or 0
    )
    ibit_px = float(ibit_data.get("current_price") or 0)

    hedge_treas = {
        **mstr_hedge,
        "strc_price": strc_px,
        "btc_price": btc_spot,
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

    strc_strip = None
    if strc_px > 0 and hedge_treas.get("strc_shares"):
        try:
            covered = strc_cash_covered_dividend_per_share(hedge_treas)
            months = usd_months_dividend_coverage(hedge_treas)
            hedge_amt = strc_hedge_amount(hedge_treas)
            from mstr_liquidation import btc_price_strc_par, btc_price_strc_zero

            btc_par = btc_price_strc_par(hedge_treas, debt_at_market=False)
            btc_zero = btc_price_strc_zero(hedge_treas, debt_at_market=False)
            strc_strip = {
                "strc_price": strc_px,
                "monthly_dividend_per_share": strc_monthly_dividend_per_share(hedge_treas),
                "cash_covered_dividend_per_share": covered,
                "usd_months_dividend_coverage": months,
                "hedge_amount_per_share": hedge_amt,
                "btc_spot": btc_spot or None,
                "btc_par": btc_par,
                "btc_zero": btc_zero,
                "buffer_to_par_pct": (
                    ((btc_par - btc_spot) / btc_spot) * 100.0
                    if btc_par is not None and btc_spot > 0
                    else None
                ),
                "buffer_to_zero_pct": (
                    ((btc_zero - btc_spot) / btc_spot) * 100.0
                    if btc_zero is not None and btc_spot > 0
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
                    ibit_price_strc_par(hedge_treas, ibit_px) if ibit_px > 0 else None
                ),
                "ibit_at_zero": (
                    ibit_price_strc_zero(hedge_treas, ibit_px) if ibit_px > 0 else None
                ),
                "ibit_spreads": [
                    {"long": float(a), "short": float(b)}
                    for a, b in hh.IBIT_HEDGE_SPREADS
                ],
            }
        except (TypeError, ValueError, KeyError, ZeroDivisionError):
            strc_strip = None

    # Prefer richer strip already on market snapshot when present
    market_strc = (market.get("mstr") or {}).get("strc_hedge")
    if isinstance(market_strc, dict) and market_strc.get("hedge_amount_per_share") is not None:
        strc_strip = {**(strc_strip or {}), **market_strc}

    market_sata = (market.get("asst") or {}).get("sata_hedge")
    sata_strip = market_sata if isinstance(market_sata, dict) else None

    three_leg = None
    if strc_px > 0 and hedge_treas.get("strc_shares"):
        three_leg = build_strc_three_leg(
            output_dir=output_dir,
            treas=hedge_treas,
            strc_px=strc_px,
            mstr_px=mstr_px,
            ibit_px=ibit_px,
            btc_spot=btc_spot,
        )

    sata_book = None
    if sata_px > 0:
        sata_book = build_sata_ibit_hedge(
            output_dir=output_dir, asst=asst, sata_px=sata_px
        )

    return {
        "btc_price": btc_spot or None,
        "STRC": strc_strip,
        "SATA": sata_strip,
        "strc_three_leg": three_leg,
        "sata_ibit": sata_book,
        "note": (
            "STRC three-leg from mstr_options_hedge.ipynb; "
            "SATA IBIT long puts from ibit_options_hedge.ipynb. "
            "$10k books, after-tax hedge cost vs total yield."
        ),
    }


if __name__ == "__main__":
    story = build_hedge_story()
    print(json.dumps({
        "strc_hedge_amt": (story.get("STRC") or {}).get("hedge_amount_per_share"),
        "winner": ((story.get("strc_three_leg") or {}).get("winner")),
        "sata_optimal": ((story.get("sata_ibit") or {}).get("optimal_strike")),
        "sata_best": ((story.get("sata_ibit") or {}).get("best")),
        "comparison": ((story.get("strc_three_leg") or {}).get("comparison")),
    }, indent=2, default=str))
