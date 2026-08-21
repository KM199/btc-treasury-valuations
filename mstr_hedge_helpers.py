"""Shared helpers for mstr_options_hedge.ipynb — theta, hedge sizing, $10k book, P&L shocks."""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from functools import reduce
from pathlib import Path
from typing import Any

import pandas as pd

from fetch_treasury_zero_yieldcurve import TreasuryZeroCurve
from ibit_option_deltas import (
    DEFAULT_DIV_YIELD,
    DEFAULT_TREE_STEPS,
    american_price_crr,
    _parse_valuation_datetime,
    year_fraction_to_expiry,
)
from mstr_liquidation import (
    STRC_PAR_VALUE,
    btc_price_strc_par,
    btc_price_strc_zero,
    ibit_price_strc_par,
    ibit_price_strc_zero,
    senior_claims_usd,
    strc_annual_dividend_per_share,
    strc_cash_covered_dividend_per_share,
    mstr_hedge_reference_strike,
    strc_hedge_amount,
    strc_monthly_dividend_per_share,
    strf_market_value_usd,
    usd_months_dividend_coverage,
)

__all__ = [
    "CAPITAL",
    "COST_OF_CAPITAL",
    "MARGINAL_TAX_RATE",
    "STRC_MARGIN_REQUIREMENT",
    "IBIT_HEDGE_SPREADS",
    "analyze_hedge_leg",
    "compute_put_spread_hedge_table",
    "put_spread_payoff_per_share",
    "btc_price_strc_par",
    "btc_price_strc_zero",
    "comparison_summary",
    "ibit_price_strc_par",
    "ibit_price_strc_zero",
    "liquidation_summary_df",
    "load_json",
    "senior_claims_usd",
    "strc_hedge_amount",
    "MSTR_MAX_COVERAGE_GAP",
    "mstr_hedge_reference_strike",
    "STRC_MAX_COVERAGE_GAP",
    "STRC_PAR_VALUE",
    "strc_put_coverage_gap",
]

COST_OF_CAPITAL = 0.0464
MARGINAL_TAX_RATE = 0.25
CAPITAL = 10_000
STRC_MARGIN_REQUIREMENT = 0.15
STRC_MAX_COVERAGE_GAP = 5.0  # max $ strike can sit below hedge_amount (e.g. $85 vs ~$90 hedge)
MSTR_MAX_COVERAGE_GAP = 8.0  # $ strike can sit below hedge reference (hedge_amount × MSTR/STRC)
CONTRACT_MULT = 100
SHOCK_PCTS = list(range(-50, 51, 10))
# Wide grid for the site's stress chart — the full ±100% spot range.
SHOCK_PCTS_WIDE = list(range(-100, 101, 10))
# IBIT vertical put spreads (long, short) near wipeout zone.
# $11 excluded — not listed on both calendar expiries (too thin to trust mids).
IBIT_EXCLUDED_PUT_STRIKES: frozenset[float] = frozenset({11.0})
IBIT_HEDGE_SPREADS: list[tuple[float, float]] = [
    (12.0, 4.0),
    (12.0, 5.0),
    (10.0, 5.0),
]


def load_json(path: str | Path) -> dict:
    with open(path) as f:
        return json.load(f)


def detect_strike_tick(strikes: list[float]) -> float:
    strikes = sorted(set(float(s) for s in strikes))
    if len(strikes) < 2:
        return 2.5
    diffs = [round(s2 - s1, 4) for s1, s2 in zip(strikes, strikes[1:]) if s2 > s1]
    diffs = [d for d in diffs if d > 0]
    if not diffs:
        return 5.0

    def _gcd(a: int, b: int) -> int:
        while b:
            a, b = b, a % b
        return a

    cents = [int(round(d * 100)) for d in diffs]
    g = reduce(_gcd, cents)
    tick = g / 100.0
    return tick if tick >= 0.01 else 2.5


def pick_theta_expirations(expirations: list[str]) -> tuple[str | None, str | None]:
    """Last two listed expirations (STRC may have fewer than MSTR/IBIT)."""
    if len(expirations) < 2:
        return None, None
    sorted_exp = sorted(expirations)
    return sorted_exp[-1], sorted_exp[-2]


def get_puts_below_price(
    expiration_date: str,
    spot: float,
    options_data: dict,
    strike_tick: float,
) -> pd.DataFrame:
    if expiration_date not in options_data:
        return pd.DataFrame()
    puts_list = options_data[expiration_date].get("puts", [])
    if not puts_list:
        return pd.DataFrame()
    puts_df = pd.DataFrame(puts_list)
    tol = max(1e-6, strike_tick * 0.01)
    on_tick = (puts_df["strike"] / strike_tick - puts_df["strike"] // strike_tick).abs() < tol
    puts_below = puts_df[(puts_df["strike"] < spot) & on_tick].copy()
    puts_below["mid_price"] = (puts_below["bid"] + puts_below["ask"]) / 2
    # Thin / after-hours chains often print 0×0 — fall back to last trade.
    zero_mid = puts_below["mid_price"] <= 0
    if "lastPrice" in puts_below.columns:
        puts_below.loc[zero_mid, "mid_price"] = puts_below.loc[zero_mid, "lastPrice"].fillna(0)
    base_cols = ["strike", "bid", "ask", "mid_price", "volume", "openInterest", "lastPrice"]
    extra = [c for c in ("delta", "gamma", "rho", "risk_free_rate", "implied_volatility") if c in puts_below.columns]
    return puts_below[base_cols + extra].copy()


def days_to_expiration(valuation_dt: datetime, expiration: str) -> int:
    exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    val_date = valuation_dt.date() if isinstance(valuation_dt, datetime) else valuation_dt
    return max((exp_date - val_date).days, 1)


def compute_theta_table_duration(
    puts: pd.DataFrame,
    expiration: str,
    valuation_dt: datetime | None = None,
) -> pd.DataFrame:
    """Theta ≈ premium / days to expiry (STRC: low volume, calendar mids unreliable)."""
    if puts.empty:
        return pd.DataFrame()
    valuation_dt = valuation_dt or datetime.now(timezone.utc)
    days = days_to_expiration(valuation_dt, expiration)
    out = puts[["strike", "mid_price"]].copy()
    out["days_to_expiration"] = days
    out["estimated_theta"] = out["mid_price"] / days
    return out.sort_values("strike").reset_index(drop=True)


def compute_theta_table(
    puts_last: pd.DataFrame,
    puts_second_last: pd.DataFrame,
    last_expiration: str,
    second_last_expiration: str,
) -> pd.DataFrame:
    if puts_last.empty or puts_second_last.empty:
        return pd.DataFrame()
    pl = puts_last[["strike", "mid_price"]].rename(columns={"mid_price": "mid_price_last"})
    if "delta" in puts_last.columns:
        pl["delta_last"] = puts_last["delta"].values
    merged = pd.merge(
        pl,
        puts_second_last[["strike", "mid_price"]].rename(columns={"mid_price": "mid_price_second_last"}),
        on="strike",
        how="inner",
    )
    if merged.empty:
        return merged
    last_exp_date = datetime.strptime(last_expiration, "%Y-%m-%d")
    second_last_exp_date = datetime.strptime(second_last_expiration, "%Y-%m-%d")
    days_difference = (last_exp_date - second_last_exp_date).days
    if days_difference <= 0:
        return pd.DataFrame()
    merged["mid_price_diff"] = merged["mid_price_last"] - merged["mid_price_second_last"]
    merged["estimated_theta"] = merged["mid_price_diff"] / days_difference
    merged["days_between"] = days_difference
    return merged.sort_values("strike").reset_index(drop=True)


def optimal_strike_continuous(spot: float, treas: dict) -> float:
    assets = treas["btc_holdings"] * treas["btc_price"] + treas["usd_reserve_usd"]
    if assets <= 0:
        return float("nan")
    return spot * senior_claims_usd(treas) / assets


def liquidation_summary_df(treas: dict, mstr_spot: float, ibit_spot: float | None) -> pd.DataFrame:
    months = usd_months_dividend_coverage(treas)
    strc_monthly = strc_monthly_dividend_per_share(treas)
    not_hedged = strc_cash_covered_dividend_per_share(treas)
    hedge = strc_hedge_amount(treas)
    btc_par = btc_price_strc_par(treas)
    btc_zero = btc_price_strc_zero(treas)
    ibit_par = ibit_price_strc_par(treas, ibit_spot) if ibit_spot is not None else None
    ibit_zero = ibit_price_strc_zero(treas, ibit_spot) if ibit_spot is not None else None
    btc_now = treas["btc_price"]
    pref_annual_m = float(treas["total_preferred_annual_dividends_usd"]) / 1e6
    cushion_par = (btc_now - btc_par) / btc_now if btc_now > 0 and btc_par is not None else float("nan")
    cushion_zero = (btc_now - btc_zero) / btc_now if btc_now > 0 and btc_zero is not None else float("nan")
    rows = [
        ["USD Reserve (strategy.com)", f"${treas['usd_reserve_usd']:,.0f}"],
        ["Preferred Annual Dividends — Stated", f"${pref_annual_m:,.1f}M"],
        ["USD Months of Dividend Coverage", f"{months:.1f}"],
        ["Convertible Debt Principal", f"${treas['convertible_debt_principal']:,.0f}"],
        ["STRF Market Value", f"${strf_market_value_usd(treas):,.0f}"],
        ["Total Senior Claims", f"${senior_claims_usd(treas):,.0f}"],
        ["STRC Price", f"${treas['strc_price']:.2f}"],
        ["STRC Monthly Coupon", f"${strc_monthly:.3f}"],
        [f"Not Hedged ({months:.1f} mo × coupon)", f"${not_hedged:.2f}"],
        ["Hedge Amount", f"${hedge:.2f}"],
        ["BTC — wipeout starts (STRC = par)", f"${btc_par:,.0f}" if btc_par is not None else "N/A"],
        ["BTC — wipeout ends (STRC = $0)", f"${btc_zero:,.0f}" if btc_zero is not None else "N/A"],
        ["Current BTC", f"${btc_now:,.0f}"],
        ["Current MSTR", f"${mstr_spot:.2f}"],
        ["MSTR — wipeout anchor (common)", "$0.00"],
        ["MSTR — hedge reference strike", f"${mstr_hedge_reference_strike(mstr_spot, treas):,.2f}"],
    ]
    if ibit_spot is not None:
        rows.extend([
            ["IBIT — wipeout starts", f"${ibit_par:.2f}" if ibit_par is not None else "N/A"],
            ["IBIT — wipeout ends", f"${ibit_zero:.2f}" if ibit_zero is not None else "N/A"],
            ["Current IBIT", f"${ibit_spot:.2f}"],
        ])
    rows.extend([
        ["BTC Cushion to Wipeout Start", f"{cushion_par:.1%}" if cushion_par == cushion_par else "N/A"],
        ["BTC Cushion to Wipeout End", f"{cushion_zero:.1%}" if cushion_zero == cushion_zero else "N/A"],
    ])
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def strc_put_coverage_gap(hedge_amount: float, strike: float) -> float:
    """$ of hedge_amount not protected until STRC falls below strike (0 if strike >= hedge)."""
    return max(0.0, hedge_amount - strike)


def put_spread_payoff_per_share(long_strike: float, short_strike: float, spot: float) -> float:
    """Intrinsic per share: long K_high put minus short K_low put."""
    return max(long_strike - spot, 0.0) - max(short_strike - spot, 0.0)


def _put_at_strike(puts: pd.DataFrame, strike: float) -> pd.Series | None:
    match = puts.loc[puts["strike"] == strike]
    return match.iloc[0] if not match.empty else None


def _estimated_theta_at_strike(
    strike: float,
    theta_merged: pd.DataFrame,
    puts_last: pd.DataFrame,
    last_expiration: str,
    valuation_dt: datetime,
) -> float:
    """Calendar theta when both expiries list the strike; else premium / days (thin legs)."""
    hit = theta_merged.loc[theta_merged["strike"] == strike, "estimated_theta"]
    if len(hit):
        return float(hit.iloc[0])
    put = _put_at_strike(puts_last, strike)
    if put is None:
        return float("nan")
    return float(put["mid_price"]) / days_to_expiration(valuation_dt, last_expiration)


def _finish_hedge_cost_columns(hedge_calc: pd.DataFrame, strc_price: float) -> pd.DataFrame:
    hedge_calc = hedge_calc.copy()
    hedge_calc["annualized_theta_cost"] = hedge_calc["estimated_theta"] * hedge_calc["contracts_needed"] * 365.25
    hedge_calc["cost_of_hedge_options"] = hedge_calc["contracts_needed"] * hedge_calc["mid_price"]
    hedge_calc["cost_of_hedged_share"] = hedge_calc["cost_of_hedge_options"] + strc_price
    hedge_calc["annualized_cost_of_capital"] = hedge_calc["cost_of_hedged_share"] * COST_OF_CAPITAL
    hedge_calc["annualized_cost_pct"] = hedge_calc["annualized_cost_of_capital"] + hedge_calc["annualized_theta_cost"]
    hedge_calc["annualized_cost_after_tax_pct"] = hedge_calc["annualized_cost_pct"] * (1 - MARGINAL_TAX_RATE)
    return hedge_calc


def compute_hedge_table(
    puts_last: pd.DataFrame,
    theta_merged: pd.DataFrame,
    hedge_amount: float,
    strc_price: float,
    *,
    max_coverage_gap: float | None = None,
    mstr_reference_strike: float | None = None,
) -> pd.DataFrame:
    if puts_last.empty or theta_merged.empty:
        return pd.DataFrame()
    hedge_calc = puts_last[["strike", "mid_price"]].copy()
    if mstr_reference_strike is not None:
        hedge_calc["coverage_gap"] = hedge_calc["strike"].map(
            lambda k: max(0.0, mstr_reference_strike - k)
        )
    else:
        hedge_calc["coverage_gap"] = hedge_calc["strike"].map(
            lambda k: strc_put_coverage_gap(hedge_amount, k)
        )
    if max_coverage_gap is not None:
        hedge_calc = hedge_calc[hedge_calc["coverage_gap"] <= max_coverage_gap].copy()
    if hedge_calc.empty:
        return pd.DataFrame()
    hedge_calc["contracts_needed"] = hedge_amount / (hedge_calc["strike"] - hedge_calc["mid_price"])
    hedge_calc = pd.merge(hedge_calc, theta_merged[["strike", "estimated_theta"]], on="strike", how="inner")
    gcols = [c for c in ("delta", "gamma", "rho", "risk_free_rate", "implied_volatility") if c in puts_last.columns]
    if gcols:
        hedge_calc = pd.merge(hedge_calc, puts_last[["strike"] + gcols], on="strike", how="left")
    return _finish_hedge_cost_columns(hedge_calc, strc_price).sort_values("strike").reset_index(drop=True)


def _put_spread_row(
    puts_last: pd.DataFrame,
    theta_merged: pd.DataFrame,
    hedge_amount: float,
    long_strike: float,
    short_strike: float,
    *,
    last_expiration: str,
    valuation_dt: datetime,
    wipeout_price: float | None = None,
) -> dict[str, Any] | None:
    """One vertical put spread row; None if legs missing or spread not viable."""
    if long_strike <= short_strike:
        return None
    if long_strike in IBIT_EXCLUDED_PUT_STRIKES or short_strike in IBIT_EXCLUDED_PUT_STRIKES:
        return None
    long_put = _put_at_strike(puts_last, long_strike)
    short_put = _put_at_strike(puts_last, short_strike)
    if long_put is None or short_put is None:
        return None

    width = long_strike - short_strike
    net_debit = float(long_put["mid_price"]) - float(short_put["mid_price"])
    max_net_payout = width - net_debit
    if max_net_payout <= 0:
        return None

    th_long = _estimated_theta_at_strike(long_strike, theta_merged, puts_last, last_expiration, valuation_dt)
    th_short = _estimated_theta_at_strike(short_strike, theta_merged, puts_last, last_expiration, valuation_dt)
    spread_theta = th_long - th_short if math.isfinite(th_long) and math.isfinite(th_short) else float("nan")

    row: dict[str, Any] = {
        "strike": long_strike,
        "short_strike": short_strike,
        "spread": f"{long_strike:g}/{short_strike:g}",
        "spread_width": width,
        "mid_price_long": float(long_put["mid_price"]),
        "mid_price_short": float(short_put["mid_price"]),
        "mid_price": net_debit,
        "contracts_needed": hedge_amount / max_net_payout,
        "estimated_theta": spread_theta,
        "max_payout_per_share": width,
        "max_net_payout_per_share": max_net_payout,
        "open_interest_long": int(long_put.get("openInterest") or 0),
        "open_interest_short": int(short_put.get("openInterest") or 0),
        "volume_long": int(long_put.get("volume") or 0),
        "volume_short": int(short_put.get("volume") or 0),
    }
    if wipeout_price is not None:
        row["payoff_at_wipeout"] = put_spread_payoff_per_share(long_strike, short_strike, wipeout_price)
    for g in ("delta", "gamma", "rho"):
        if g in long_put.index and g in short_put.index and pd.notna(long_put[g]) and pd.notna(short_put[g]):
            row[g] = float(long_put[g]) - float(short_put[g])
    if "risk_free_rate" in long_put.index and pd.notna(long_put["risk_free_rate"]):
        row["risk_free_rate"] = float(long_put["risk_free_rate"])
    if "implied_volatility" in long_put.index and pd.notna(long_put["implied_volatility"]):
        row["implied_volatility"] = float(long_put["implied_volatility"])
    if "implied_volatility" in short_put.index and pd.notna(short_put["implied_volatility"]):
        row["implied_volatility_short"] = float(short_put["implied_volatility"])
    return row


def compute_put_spread_hedge_table(
    puts_last: pd.DataFrame,
    theta_merged: pd.DataFrame,
    hedge_amount: float,
    strc_price: float,
    *,
    last_expiration: str,
    valuation_dt: datetime | None = None,
    spread_pairs: list[tuple[float, float]] | None = None,
    wipeout_price: float | None = None,
) -> pd.DataFrame:
    """Size each listed vertical put spread to cover hedge_amount."""
    spread_pairs = spread_pairs or IBIT_HEDGE_SPREADS
    valuation_dt = valuation_dt or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for long_strike, short_strike in spread_pairs:
        row = _put_spread_row(
            puts_last, theta_merged, hedge_amount, long_strike, short_strike,
            last_expiration=last_expiration,
            valuation_dt=valuation_dt,
            wipeout_price=wipeout_price,
        )
        if row is not None:
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return _finish_hedge_cost_columns(out, strc_price).sort_values(
        ["strike", "short_strike"], ascending=[False, True]
    ).reset_index(drop=True)


def compute_book_table(hedge_calc: pd.DataFrame, treas: dict) -> pd.DataFrame:
    if hedge_calc.empty:
        return hedge_calc
    strc_yield = strc_annual_dividend_per_share(treas)
    out = hedge_calc.copy()
    out["capital_per_share"] = (
        out["mid_price"] * out["contracts_needed"] + STRC_MARGIN_REQUIREMENT * treas["strc_price"]
    )
    out["num_shares"] = CAPITAL / out["capital_per_share"]
    out["dividend"] = out["num_shares"] * strc_yield
    out["total_purchase"] = out["num_shares"] * (treas["strc_price"] + out["cost_of_hedge_options"])
    out["borrow_cost"] = -(out["total_purchase"] - CAPITAL) * COST_OF_CAPITAL
    out["theta_cost"] = -out["annualized_theta_cost"] * out["num_shares"]
    out["tax_benefit"] = (-MARGINAL_TAX_RATE) * (out["theta_cost"] + out["borrow_cost"])
    out["hedge_cost_after_tax"] = -(out["theta_cost"] + out["borrow_cost"] + out["tax_benefit"])
    out["total_yield"] = out["dividend"] + out["theta_cost"] + out["borrow_cost"] + out["tax_benefit"]
    out["total_cash_flow"] = out["dividend"] + out["borrow_cost"] + out["theta_cost"]
    return out


def _load_treasury_zero_curve(data: dict, yield_curve_path: str | Path = "output/yield_curve.json"):
    raw = data.get("treasury_zero_curve")
    if isinstance(raw, dict) and raw.get("pillars_years"):
        try:
            return TreasuryZeroCurve.from_saved_dict(raw), "embedded treasury_zero_curve"
        except Exception:
            pass
    try:
        with open(yield_curve_path) as f:
            raw = json.load(f)
        if isinstance(raw, dict) and raw.get("pillars_years"):
            return TreasuryZeroCurve.from_saved_dict(raw), str(yield_curve_path)
    except Exception:
        pass
    return None, None


def compute_pnl_sensitivity(
    hedge_calc: pd.DataFrame,
    spot: float,
    last_expiration: str,
    data: dict,
    *,
    yield_curve_path: str | Path = "output/yield_curve.json",
    shock_pcts: list[int] | None = None,
) -> pd.DataFrame:
    if hedge_calc.empty or "delta" not in hedge_calc.columns or not hedge_calc["delta"].notna().any():
        return pd.DataFrame()
    shocks = list(shock_pcts) if shock_pcts else SHOCK_PCTS
    curve_rf, _ = _load_treasury_zero_curve(data, yield_curve_path)
    ts = data.get("timestamp")
    valuation_dt = _parse_valuation_datetime(str(ts)) if ts else datetime.now(timezone.utc)
    T_last = None
    r_eq_last = None
    try:
        T_last = year_fraction_to_expiry(valuation_dt, date.fromisoformat(last_expiration))
    except Exception:
        T_last = None
    if curve_rf is not None and T_last is not None:
        r_eq_last = curve_rf.equivalent_constant_rate(T_last)
        if not math.isfinite(r_eq_last):
            r_eq_last = None

    rows: list[dict[str, Any]] = []
    S0 = float(spot)
    for _, row in hedge_calc.iterrows():
        n_sh = float(row["num_shares"])
        n_per_share = float(row["contracts_needed"])
        n_listed = n_sh * n_per_share / CONTRACT_MULT
        strike_label = (
            f"{row['strike']:.0f}/{row['short_strike']:.0f}"
            if pd.notna(row.get("short_strike")) else row["strike"]
        )
        rec: dict[str, Any] = {
            "Strike": strike_label,
            "Delta": float("nan"),
            "Num shares": round(n_sh, 2),
            "Option contracts": round(n_listed, 4),
        }
        if pd.isna(row.get("delta")):
            for p in shocks:
                rec[f"{p:+d}%"] = float("nan")
            rows.append(rec)
            continue
        dlt = float(row["delta"])
        rec["Delta"] = round(dlt, 4)
        if pd.notna(row.get("risk_free_rate")):
            ri = float(row["risk_free_rate"])
        elif r_eq_last is not None:
            ri = r_eq_last
        else:
            ri = float("nan")
        iv_raw = row.get("implied_volatility")
        use_full = T_last is not None and pd.notna(iv_raw) and float(iv_raw) > 0 and math.isfinite(ri)
        if use_full:
            K = float(row["strike"])
            sig = float(iv_raw)
            K_short = row.get("short_strike")
            is_spread = pd.notna(K_short)
            if is_spread:
                K_short = float(K_short)
                sig_short = row.get("implied_volatility_short")
                sig_s = float(sig_short) if pd.notna(sig_short) and float(sig_short) > 0 else sig
            V0_long = american_price_crr(S0, K, T_last, ri, DEFAULT_DIV_YIELD, sig, n_steps=DEFAULT_TREE_STEPS, is_call=False)
            V0 = V0_long
            if is_spread:
                V0_short = american_price_crr(
                    S0, K_short, T_last, ri, DEFAULT_DIV_YIELD, sig_s,
                    n_steps=DEFAULT_TREE_STEPS, is_call=False,
                )
                V0 = V0_long - V0_short
            for p in shocks:
                h = p / 100.0
                S1 = S0 * (1 + h)
                r1 = ri * (1 + h)
                V1_long = american_price_crr(
                    S1, K, T_last, r1, DEFAULT_DIV_YIELD, sig,
                    n_steps=DEFAULT_TREE_STEPS, is_call=False,
                )
                if is_spread:
                    V1_short = american_price_crr(
                        S1, K_short, T_last, r1, DEFAULT_DIV_YIELD, sig_s,
                        n_steps=DEFAULT_TREE_STEPS, is_call=False,
                    )
                    V1 = V1_long - V1_short
                else:
                    V1 = V1_long
                rec[f"{p:+d}%"] = n_listed * CONTRACT_MULT * (V1 - V0) if math.isfinite(V1) else float("nan")
        else:
            gam = float(row["gamma"]) if pd.notna(row.get("gamma")) else 0.0
            rho = float(row["rho"]) if pd.notna(row.get("rho")) else 0.0
            for p in shocks:
                h = p / 100.0
                dS = h * S0
                dr = h * ri
                dPi = dlt * dS + 0.5 * gam * dS * dS + rho * dr
                rec[f"{p:+d}%"] = n_listed * CONTRACT_MULT * dPi
        rows.append(rec)
    return pd.DataFrame(rows)


def analyze_hedge_leg(
    leg_name: str,
    data: dict,
    options: dict,
    treas: dict,
    *,
    spot: float | None = None,
    wipeout_price: float | None = None,
) -> dict[str, Any]:
    """Run theta + hedge sizing for one put-underlying leg."""
    spot = float(spot if spot is not None else data["current_price"])
    chain = data.get("options_data") or options
    expirations = data.get("expirations") or sorted(chain.keys())
    is_strc_leg = "STRC" in leg_name.upper()
    is_mstr_leg = "MSTR" in leg_name.upper()
    is_ibit_leg = "IBIT" in leg_name.upper()
    use_duration_theta = is_strc_leg or is_mstr_leg
    sorted_exp = sorted(expirations)
    last_exp = sorted_exp[-1] if sorted_exp else None
    second_last = sorted_exp[-2] if len(sorted_exp) >= 2 else None
    result: dict[str, Any] = {
        "leg": leg_name,
        "spot": spot,
        "last_expiration": last_exp,
        "second_last_expiration": second_last,
        "theta": pd.DataFrame(),
        "hedge_calc": pd.DataFrame(),
        "book": pd.DataFrame(),
        "pnl": pd.DataFrame(),
    }
    if last_exp is None:
        return result
    if not use_duration_theta and not is_ibit_leg and second_last is None:
        return result

    sample_puts: list[float] = []
    exp_samples = (last_exp,) if use_duration_theta else (last_exp, second_last)
    for exp in exp_samples:
        if exp in chain:
            sample_puts.extend(p["strike"] for p in chain[exp].get("puts", []) if p["strike"] < spot)
    strike_tick = detect_strike_tick(sample_puts)
    result["strike_tick"] = strike_tick

    puts_last = get_puts_below_price(last_exp, spot, chain, strike_tick)
    ts = data.get("timestamp")
    valuation_dt = _parse_valuation_datetime(str(ts)) if ts else datetime.now(timezone.utc)
    if use_duration_theta:
        theta = compute_theta_table_duration(puts_last, last_exp, valuation_dt)
    else:
        puts_second_last = get_puts_below_price(second_last, spot, chain, strike_tick)
        theta = compute_theta_table(puts_last, puts_second_last, last_exp, second_last)
    result["theta"] = theta

    hedge_amount = strc_hedge_amount(treas)
    result["hedge_amount"] = hedge_amount
    mstr_ref = mstr_hedge_reference_strike(spot, treas) if is_mstr_leg else None
    if is_mstr_leg:
        wipeout_price = 0.0
    result["wipeout_price"] = wipeout_price
    if is_mstr_leg:
        result["hedge_reference_strike"] = mstr_ref
    else:
        result["optimal_strike"] = optimal_strike_continuous(spot, treas)

    if is_ibit_leg:
        hedge_calc = compute_put_spread_hedge_table(
            puts_last, theta, hedge_amount, treas["strc_price"],
            last_expiration=last_exp,
            valuation_dt=valuation_dt,
            wipeout_price=wipeout_price,
        )
        result["hedge_structure"] = "put_spreads"
        spread_strikes = sorted({s for pair in IBIT_HEDGE_SPREADS for s in pair})
        if not puts_last.empty:
            leg_puts = puts_last[puts_last["strike"].isin(spread_strikes)].copy()
            leg_puts["estimated_theta"] = [
                _estimated_theta_at_strike(s, theta, puts_last, last_exp, valuation_dt)
                for s in leg_puts["strike"]
            ]
            result["theta"] = leg_puts.sort_values("strike").reset_index(drop=True)
    else:
        hedge_calc = compute_hedge_table(
            puts_last, theta, hedge_amount, treas["strc_price"],
            max_coverage_gap=(
                STRC_MAX_COVERAGE_GAP if is_strc_leg
                else MSTR_MAX_COVERAGE_GAP if is_mstr_leg
                else None
            ),
            mstr_reference_strike=mstr_ref,
        )
        result["hedge_structure"] = "long_put"
        if (is_strc_leg or is_mstr_leg) and not hedge_calc.empty and not theta.empty:
            viable = set(hedge_calc["strike"])
            if "strike" in theta.columns:
                result["theta"] = theta[theta["strike"].isin(viable)].reset_index(drop=True)
    result["hedge_calc"] = hedge_calc
    if not hedge_calc.empty:
        result["book"] = compute_book_table(hedge_calc, treas)
        # STRC: skip parallel % shocks — price is floored near par ($100), upside P&L is not meaningful.
        if "num_shares" in result["book"].columns and not is_strc_leg:
            result["pnl"] = compute_pnl_sensitivity(result["book"], spot, last_exp, data)
    return result


def comparison_summary(leg_results: list[dict[str, Any]]) -> pd.DataFrame:
    """One row per leg: best strike by max $10k book total yield (same row for cost & yield)."""
    rows = []
    for leg in leg_results:
        hc = leg.get("hedge_calc")
        book = leg.get("book")
        if hc is None or hc.empty or book is None or book.empty:
            rows.append({
                "Leg": leg["leg"],
                "Expirations": f"{leg.get('last_expiration', 'N/A')}",
                "Strikes": len(hc) if hc is not None and not hc.empty else 0,
                "Best Strike": None,
                "Hedge Cost ($10k)": None,
                "Total Yield ($10k)": None,
            })
            continue
        best = book.loc[book["total_yield"].idxmax()]
        if pd.notna(best.get("short_strike")):
            best_strike: str | float = best.get("spread") or f"{best['strike']:.0f}/{best['short_strike']:.0f}"
        else:
            best_strike = best["strike"]
        rows.append({
            "Leg": leg["leg"],
            "Expirations": f"{leg.get('second_last_expiration')} → {leg.get('last_expiration')}",
            "Strikes": len(hc),
            "Best Strike": best_strike,
            "Hedge Cost ($10k)": round(float(best["hedge_cost_after_tax"]), 2),
            "Total Yield ($10k)": round(float(best["total_yield"]), 2),
        })
    return pd.DataFrame(rows)
