#!/usr/bin/env python3
"""
American (CRR binomial) implied vol from option mid, then delta and gamma via spot bumps.

Enriches each contract in ibit_data.json (and mirrors ibit_options.json) with:
  mid_price, implied_volatility, delta, gamma, rho, risk_free_rate

Gamma Γ = ∂²V/∂S² = ∂Δ/∂S. Rho = ∂V/∂r (per 1.0 continuous r; same σ; central bump in r).

Run after fetch_data (or whenever chains are updated):
  python ibit_option_deltas.py

By default loads yield_curve.json from fetch_data.py; if missing, pulls FRED live.
See fetch_treasury_zero_yieldcurve.py. Override with --flat-risk-free 0.042.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import requests

from fetch_treasury_zero_yieldcurve import (
    TreasuryZeroCurve,
    load_yield_curve_json,
    try_build_treasury_zero_curve,
)

from strc_paths import OUTPUT_DIR as DEFAULT_OUTPUT_DIR

DEFAULT_RISK_FREE = 0.042
DEFAULT_DIV_YIELD = 0.0
DEFAULT_TREE_STEPS = 128
IV_LOW = 1e-5
IV_HIGH = 5.0
IV_ITERS = 48
PRICE_TOL = 5e-4

# Central FD on the CRR tree: a single ~1e-4·S bump makes Γ = (V+−2V0+V−)/h² numerically ~0
# (second differences sit in tree/rounding noise). Use a wider bump for Γ only; keep a smaller bump for Δ.
FD_SPOT_DELTA_FRAC = 1e-3
FD_SPOT_GAMMA_FRAC = 2e-3
FD_DELTA_ABS_FLOOR = 1e-5
FD_GAMMA_ABS_FLOOR = 2e-2  # dollars; ensures OTM names still get a stable Γ stencil on coarse trees


def _iso_expiration_keys(options_data: dict[str, Any]) -> list[str]:
    """Sorted YYYY-MM-DD keys only (same skips as enrichment loop)."""
    keys: list[str] = []
    for k in options_data.keys():
        if not isinstance(k, str):
            continue
        try:
            date.fromisoformat(k)
        except ValueError:
            continue
        keys.append(k)
    keys.sort()
    return keys


def _option_row_count(block: Any) -> int:
    if not isinstance(block, dict):
        return 0
    return len(block.get("calls") or []) + len(block.get("puts") or [])


def _parse_valuation_datetime(ts: str) -> datetime:
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def year_fraction_to_expiry(valuation: datetime, expiration: date) -> float:
    """Calendar year fraction to expiry session; floored for numerical stability."""
    exp_dt = datetime(
        expiration.year, expiration.month, expiration.day, 21, 0, 0, tzinfo=valuation.tzinfo
    )
    seconds = (exp_dt - valuation).total_seconds()
    if seconds <= 0:
        seconds = 3600.0  # treat as ~1h if clock is past modeled expiry
    T = seconds / (365.25 * 24 * 3600)
    return max(T, 1.0 / (365.25 * 24))  # at least ~one hour


def american_price_crr(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
    *,
    n_steps: int,
    is_call: bool,
) -> float:
    """American option value (CRR binomial), continuous yield q."""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0 or n_steps < 2:
        return float("nan")

    n = int(n_steps)
    dt = T / n
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    disc = math.exp(-r * dt)
    growth = math.exp((r - q) * dt)
    p = (growth - d) / (u - d)
    p = min(max(p, 0.0), 1.0)

    j = np.arange(n + 1, dtype=np.float64)
    stock = S * (u ** (n - j)) * (d**j)
    if is_call:
        V = np.maximum(stock - K, 0.0)
    else:
        V = np.maximum(K - stock, 0.0)

    for i in range(n - 1, -1, -1):
        j = np.arange(i + 1, dtype=np.float64)
        stock = S * (u ** (i - j)) * (d**j)
        cont = disc * (p * V[:-1] + (1.0 - p) * V[1:])
        if is_call:
            intrinsic = np.maximum(stock - K, 0.0)
        else:
            intrinsic = np.maximum(K - stock, 0.0)
        V = np.maximum(intrinsic, cont)
    return float(V[0])


def implied_vol_bisection(
    target: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    *,
    n_steps: int,
    is_call: bool,
) -> float | None:
    """Sigma such that American tree price ~= target (mid)."""
    if not math.isfinite(target) or target <= 0:
        return None

    lo, hi = IV_LOW, IV_HIGH
    pl = american_price_crr(S, K, T, r, q, lo, n_steps=n_steps, is_call=is_call)
    ph = american_price_crr(S, K, T, r, q, hi, n_steps=n_steps, is_call=is_call)
    if any(not math.isfinite(x) for x in (pl, ph)):
        return None
    if target < pl - 1e-6 or target > ph + 1e-3:
        return None

    for _ in range(IV_ITERS):
        mid = 0.5 * (lo + hi)
        pm = american_price_crr(S, K, T, r, q, mid, n_steps=n_steps, is_call=is_call)
        if not math.isfinite(pm):
            hi = mid
            continue
        if abs(pm - target) < PRICE_TOL:
            return mid
        if pm < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            return mid
    return 0.5 * (lo + hi)


def american_delta_gamma(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
    *,
    n_steps: int,
    is_call: bool,
) -> tuple[float | None, float | None]:
    """Central FD on S (fixed σ): Δ from a fine bump, Γ from a wider bump (stable on CRR trees)."""
    h_d = max(S * FD_SPOT_DELTA_FRAC, FD_DELTA_ABS_FLOOR)
    h_g = max(S * FD_SPOT_GAMMA_FRAC, FD_GAMMA_ABS_FLOOR)
    v0 = american_price_crr(S, K, T, r, q, sigma, n_steps=n_steps, is_call=is_call)
    pu_d = american_price_crr(S + h_d, K, T, r, q, sigma, n_steps=n_steps, is_call=is_call)
    md_d = american_price_crr(S - h_d, K, T, r, q, sigma, n_steps=n_steps, is_call=is_call)
    pu_g = american_price_crr(S + h_g, K, T, r, q, sigma, n_steps=n_steps, is_call=is_call)
    md_g = american_price_crr(S - h_g, K, T, r, q, sigma, n_steps=n_steps, is_call=is_call)
    if not all(
        math.isfinite(x) for x in (v0, pu_d, md_d, pu_g, md_g)
    ):
        return None, None
    delta = (pu_d - md_d) / (2.0 * h_d)
    gamma = (pu_g - 2.0 * v0 + md_g) / (h_g * h_g)
    return delta, gamma


def american_rho_bumped(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
    *,
    n_steps: int,
    is_call: bool,
) -> float | None:
    """∂V/∂r per unit continuous r (central finite difference on American tree)."""
    dr = max(1e-8, abs(r) * 1e-4 + 1e-8)
    vp = american_price_crr(S, K, T, r + dr, q, sigma, n_steps=n_steps, is_call=is_call)
    vm = american_price_crr(S, K, T, r - dr, q, sigma, n_steps=n_steps, is_call=is_call)
    if not (math.isfinite(vp) and math.isfinite(vm)):
        return None
    return (vp - vm) / (2.0 * dr)


def option_mid(bid: Any, ask: Any) -> float | None:
    try:
        b = float(bid)
        a = float(ask)
    except (TypeError, ValueError):
        return None
    if b <= 0 or a <= 0 or a < b:
        return None
    return 0.5 * (b + a)


def enrich_contract(
    row: dict[str, Any],
    *,
    S: float,
    T: float,
    r: float,
    q: float,
    n_steps: int,
    is_call: bool,
) -> None:
    mid = option_mid(row.get("bid"), row.get("ask"))
    row["mid_price"] = mid
    row["risk_free_rate"] = r if math.isfinite(r) else None
    if mid is None:
        row["implied_volatility"] = None
        row["delta"] = None
        row["gamma"] = None
        row["rho"] = None
        return

    iv = implied_vol_bisection(mid, S, float(row["strike"]), T, r, q, n_steps=n_steps, is_call=is_call)
    row["implied_volatility"] = iv
    if iv is None:
        row["delta"] = None
        row["gamma"] = None
        row["rho"] = None
        return

    dlt, gam = american_delta_gamma(S, float(row["strike"]), T, r, q, iv, n_steps=n_steps, is_call=is_call)
    row["delta"] = dlt
    row["gamma"] = gam
    row["rho"] = american_rho_bumped(S, float(row["strike"]), T, r, q, iv, n_steps=n_steps, is_call=is_call)


def enrich_options_data(
    options_data: dict[str, Any],
    *,
    current_price: float,
    valuation: datetime,
    curve: TreasuryZeroCurve | None,
    flat_r: float | None,
    q: float,
    n_steps: int,
    log: bool = True,
) -> tuple[int, int]:
    """Mutates options_data in place. Returns (contracts_enriched, contracts_skipped)."""
    ok = 0
    skipped = 0
    exp_keys = _iso_expiration_keys(options_data)
    n_exp = len(exp_keys)
    total_rows = sum(_option_row_count(options_data[k]) for k in exp_keys)
    if log and n_exp:
        print(
            f"Enriching {n_exp} expirations ({total_rows} option rows), spot={current_price:.4f} …",
            flush=True,
        )
    for idx, exp_str in enumerate(exp_keys, start=1):
        block = options_data[exp_str]
        exp_date = date.fromisoformat(exp_str)
        T = year_fraction_to_expiry(valuation, exp_date)
        if curve is not None:
            r_T = curve.equivalent_constant_rate(T)
            if not math.isfinite(r_T):
                r_T = flat_r if flat_r is not None else DEFAULT_RISK_FREE
        else:
            r_T = flat_r if flat_r is not None else DEFAULT_RISK_FREE
        ok0, sk0 = ok, skipped
        for side in ("calls", "puts"):
            rows = block.get(side) or []
            is_call = side == "calls"
            for row in rows:
                if "strike" not in row:
                    skipped += 1
                    continue
                enrich_contract(row, S=current_price, T=T, r=r_T, q=q, n_steps=n_steps, is_call=is_call)
                if row.get("delta") is not None:
                    ok += 1
                else:
                    skipped += 1
        if log:
            priced = ok - ok0
            sk = skipped - sk0
            print(
                f"  [{idx}/{n_exp}] {exp_str}  T={T:.4f}y  r={r_T:.4f}  "
                f"priced {priced}  skipped {sk}",
                flush=True,
            )
    return ok, skipped


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def main() -> None:
    p = argparse.ArgumentParser(description="Add American binomial delta (from mid) to IBIT JSON.")
    p.add_argument("--ibit-data", type=Path, default=DEFAULT_OUTPUT_DIR / "ibit_data.json")
    p.add_argument("--ibit-options", type=Path, default=DEFAULT_OUTPUT_DIR / "ibit_options.json")
    p.add_argument(
        "--flat-risk-free",
        type=float,
        default=None,
        metavar="R",
        help="Skip FRED/Treasury curve and use this constant continuous rate (e.g. 0.042)",
    )
    p.add_argument(
        "--risk-free",
        type=float,
        default=None,
        help="Deprecated alias for --flat-risk-free when curve fetch fails (ignored if curve ok)",
    )
    p.add_argument("--div-yield", type=float, default=DEFAULT_DIV_YIELD, help="Continuous dividend yield on IBIT")
    p.add_argument("--tree-steps", type=int, default=DEFAULT_TREE_STEPS, help="Binomial steps (speed vs accuracy)")
    p.add_argument(
        "--yield-curve",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "yield_curve.json",
        help=f"Path from fetch_data.py (default: {DEFAULT_OUTPUT_DIR / 'yield_curve.json'})",
    )
    p.add_argument("--dry-run", action="store_true", help="Compute but do not write files")
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress per-expiration progress lines")
    args = p.parse_args()

    flat_r = args.flat_risk_free
    if args.risk_free is not None and flat_r is None:
        flat_r = args.risk_free

    if not args.ibit_data.is_file():
        print(f"Missing {args.ibit_data}", file=sys.stderr)
        sys.exit(1)

    data = load_json(args.ibit_data)
    spot = data.get("current_price")
    if spot is None or not math.isfinite(float(spot)):
        print("ibit_data.json has no valid current_price", file=sys.stderr)
        sys.exit(1)
    S = float(spot)

    ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
    valuation = _parse_valuation_datetime(str(ts))

    od = data.get("options_data")
    if not isinstance(od, dict):
        print("ibit_data.json missing options_data", file=sys.stderr)
        sys.exit(1)

    curve: TreasuryZeroCurve | None = None
    curve_how: str | None = None
    if flat_r is None:
        curve, err_file = load_yield_curve_json(args.yield_curve)
        if curve is not None:
            curve_how = f"{args.yield_curve} (saved)"
        else:
            sess = requests.Session()
            curve, err_live = try_build_treasury_zero_curve(session=sess)
            if curve is not None:
                curve_how = "live FRED (yield_curve.json missing or invalid)"
            else:
                msg = "; ".join(x for x in (err_file, err_live) if x)
                print(
                    f"Warning: no yield curve ({msg}). Using flat rate {DEFAULT_RISK_FREE}.",
                    file=sys.stderr,
                )
                flat_r = DEFAULT_RISK_FREE
                data.pop("treasury_zero_curve", None)
    else:
        curve = None
        data.pop("treasury_zero_curve", None)

    fallback_rate = flat_r if flat_r is not None else DEFAULT_RISK_FREE

    ok, skipped = enrich_options_data(
        od,
        current_price=S,
        valuation=valuation,
        curve=curve,
        flat_r=fallback_rate,
        q=args.div_yield,
        n_steps=args.tree_steps,
        log=not args.quiet,
    )
    print(f"Spot: {S:.4f}  valuation: {valuation.isoformat()}")
    if curve is not None:
        print(f"Treasury curve: {curve_how}  FRED as-of: {curve.as_of_date}")
        data["treasury_zero_curve"] = curve.to_json_dict()
    else:
        print(f"Flat risk-free (continuous): {fallback_rate:.6f}")
    print(f"Div yield: {args.div_yield:.4f}  tree steps: {args.tree_steps}")
    print(f"Contracts with delta: {ok}  without / skipped: {skipped}")

    if args.dry_run:
        return

    save_json(args.ibit_data, data)

    if args.ibit_options.is_file():
        save_json(args.ibit_options, od)
        print(f"Updated {args.ibit_options}")

    print(f"Updated {args.ibit_data}")


if __name__ == "__main__":
    main()
