#!/usr/bin/env python3
"""
American (CRR binomial) implied vol from option mid, then delta and gamma via spot bumps.

Enriches each contract in ibit_data.json (and mirrors ibit_options.json) with:
  mid_price, implied_volatility, delta, gamma, rho, risk_free_rate

Gamma Γ = ∂²V/∂S² = ∂Δ/∂S. Rho = ∂V/∂r (per 1.0 continuous r; same σ; central bump in r).

Normally run automatically via fetch_data.py; standalone:
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
# Yield for names that genuinely pay nothing (IBIT, MSTR). Imported directly by
# hedge_story.py / mstr_hedge_helpers.py, which only price those two. It is NOT a
# fallback for a missing yield — see resolve_dividend_yield below.
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

# --- Dividend yield policy --------------------------------------------------
# The CRR tree models a continuous *proportional* yield: F = S·e^{(r−q)T}. q is
# therefore a yield on SPOT, never a coupon on par. Letting a missing q silently
# become 0.0 on a ~12% payer overstates put IV by 4–9 vol points (and corrupts the
# Δ/Γ/ρ solved off that IV), so every ticker is classified rather than defaulted.
PREFERRED_STATED_AMOUNT = 100.0  # $100 stated amount on the Strategy/Strive preferreds

# Pay nothing — q = 0 is the answer here, not a fallback.
#   IBIT: spot-BTC ETF, no distributions.  MSTR: common stock, no dividend.
NON_DIVIDEND_TICKERS = frozenset({"ibit", "mstr"})

# Known large payers — a missing yield is a data failure, not a zero.
DIVIDEND_PAYING_TICKERS = frozenset({"strc", "strd", "stre", "strf", "strk", "sata"})

# Treasury JSONs carrying "<ticker>_dividend_rate" / "<ticker>_effective_yield", in
# preference order. fetch_mstr_treasury.py keeps these alive via
# data.strategytracker.com when strategy.com 403s the scrape.
TREASURY_YIELD_SOURCES = ("mstr_treasury_extracted_data.json", "mstr_strategy_raw.json")

# dividend_yield_source values meaning "we gave up and used zero" — Greeks stored
# under these are not trustworthy for a dividend payer.
UNTRUSTED_DIVIDEND_SOURCES = frozenset({"MISSING-assumed-zero", "unknown-ticker-assumed-zero"})


class MissingDividendYieldError(ValueError):
    """A ticker known to pay a dividend has no resolvable yield on spot."""


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
    if T <= 0 or sigma <= 0 or S < 0 or K <= 0 or n_steps < 2:
        return float("nan")
    if S == 0:
        # Dead underlying — the lattice is multiplicative and degenerates here.
        # An American put is exercised immediately for K; a call is worthless.
        return 0.0 if is_call else float(K)

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


def is_options_chain_enriched(data_path: Path) -> bool:
    """True if on-disk ticker JSON already has delta/IV on option rows."""
    if not data_path.is_file():
        return False
    try:
        data = load_json(data_path)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    od = data.get("options_data")
    if not isinstance(od, dict):
        return False
    # A payer's chain enriched at q=0 (or before dividend_yield_source existed) has
    # deltas, but wrong ones — treat it as unenriched so the next run repairs it.
    if _ticker_from_data_path(data_path) in DIVIDEND_PAYING_TICKERS:
        source = data.get("dividend_yield_source")
        try:
            stored_q = float(data.get("dividend_yield"))
        except (TypeError, ValueError):
            stored_q = 0.0
        if not source or source in UNTRUSTED_DIVIDEND_SOURCES or stored_q <= 0.0:
            return False
    checked = 0
    with_delta = 0
    for exp_str in _iso_expiration_keys(od):
        block = od[exp_str]
        for side in ("calls", "puts"):
            for row in block.get(side) or []:
                if "strike" not in row:
                    continue
                checked += 1
                if row.get("delta") is not None:
                    with_delta += 1
    return checked > 0 and with_delta > 0


def _ticker_from_data_path(data_path: Path) -> str:
    """'output/strc_data.json' -> 'strc'."""
    stem = data_path.stem.lower()
    return stem[:-5] if stem.endswith("_data") else stem


def yield_on_spot_from_par_rate(rate: float, spot: float, par: float = PREFERRED_STATED_AMOUNT) -> float:
    """Coupon on the stated amount -> current yield on the traded price.

    STRC pays a fixed *cash* 12% of the $100 stated amount ($1.00/month), whatever the
    stock trades at, so the stated rate is not a yield on spot: at $98.67 the cash
    stream is 12.00/98.67 = 12.16%. Matching the tree's forward S·e^{−qT} to the cash
    actually paid over T gives q ≈ D/S, so the simple current yield is the right
    continuous q here. Compounding refinements (−12·ln(1 − D/12S) = 12.22%, or
    ln(1 + D/S) = 11.48% if the payout were annual rather than monthly) move solved IV
    by ≤0.10 and −0.35 vol points respectively — immaterial next to the 4–9 points lost
    to q = 0, and the annual convention is wrong for a monthly payer anyway.
    """
    if spot <= 0:
        raise ValueError(f"cannot convert a par rate to a yield on spot={spot!r}")
    return float(rate) * float(par) / float(spot)


def _fractional_rate(value: Any) -> float | None:
    """Accept 12 or 0.12; reject junk and implausible magnitudes."""
    try:
        r = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(r):
        return None
    if r > 1.0:  # supplied as a percentage
        r /= 100.0
    return r if 0.0 < r <= 0.5 else None


def _treasury_dividend_yield(ticker: str, spot: float, output_dir: Path) -> tuple[float, str] | None:
    """Current yield on ``spot`` for a $100-par preferred, from the treasury JSONs.

    Prefers ``<ticker>_dividend_rate`` (the coupon on par, rescaled onto live spot) over
    ``<ticker>_effective_yield``. The latter is the same current yield but computed at
    the scraper's own, staler, price — e.g. 12.00/98.5455 = 12.177% against 12.00/98.67 =
    12.162% at the spot the tree is actually using.
    """
    if spot <= 0:
        return None
    for name in TREASURY_YIELD_SOURCES:
        path = output_dir / name
        if not path.is_file():
            continue
        try:
            blob = load_json(path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(blob, dict):
            continue
        rate = _fractional_rate(blob.get(f"{ticker}_dividend_rate"))
        if rate is not None:
            return yield_on_spot_from_par_rate(rate, spot), f"{name}:{ticker}_dividend_rate×par/spot"
        eff = _fractional_rate(blob.get(f"{ticker}_effective_yield"))
        if eff is not None:
            return eff, f"{name}:{ticker}_effective_yield"
    return None


def resolve_dividend_yield(
    ticker: str,
    data: dict[str, Any],
    spot: float,
    *,
    output_dir: Path,
    override: float | None = None,
    strict: bool = True,
) -> tuple[float, str]:
    """Continuous dividend yield on spot, plus a provenance label for the JSON.

    Precedence: explicit override, then a ``dividend_yield`` already on the ticker JSON,
    then the treasury JSONs. Raises :class:`MissingDividendYieldError` (unless
    ``strict=False``) rather than quietly pricing a known payer at q = 0.
    """
    t = ticker.lower()

    if override is not None:
        return float(override), "override:--div-yield"

    raw_q = data.get("dividend_yield")
    if raw_q is not None:
        try:
            q = float(raw_q)
        except (TypeError, ValueError):
            q = float("nan")
        # A stored 0.0 (or junk) on a known payer is the old silent fallback, not data.
        if math.isfinite(q) and (q > 0.0 or t not in DIVIDEND_PAYING_TICKERS):
            source = data.get("dividend_yield_source")
            return q, str(source) if source else f"{t}_data.json:dividend_yield"

    if t in DIVIDEND_PAYING_TICKERS:
        found = _treasury_dividend_yield(t, spot, output_dir)
        if found is not None:
            return found
        msg = (
            f"{t.upper()} pays a dividend but no yield on spot could be resolved: "
            f"{t}_data.json carries no usable 'dividend_yield' (strategy.com 403?) and none of "
            f"{', '.join(TREASURY_YIELD_SOURCES)} under {output_dir} carry "
            f"{t}_dividend_rate / {t}_effective_yield. Run fetch_mstr_treasury.py, or pass "
            "--div-yield. Pricing at q=0 would overstate implied vol by several points."
        )
        if strict:
            raise MissingDividendYieldError(msg)
        print(f"Warning: {msg}", file=sys.stderr)
        return DEFAULT_DIV_YIELD, "MISSING-assumed-zero"

    if t in NON_DIVIDEND_TICKERS:
        return DEFAULT_DIV_YIELD, "none-expected"

    print(
        f"Warning: {t.upper()} has no 'dividend_yield' and no policy entry; assuming q=0. "
        "Add it to NON_DIVIDEND_TICKERS or DIVIDEND_PAYING_TICKERS in ibit_option_deltas.py.",
        file=sys.stderr,
    )
    return DEFAULT_DIV_YIELD, "unknown-ticker-assumed-zero"


def enrich_options_files(
    data_path: Path,
    options_path: Path,
    *,
    yield_curve_path: Path | None = None,
    flat_risk_free: float | None = None,
    div_yield: float | None = None,
    tree_steps: int = DEFAULT_TREE_STEPS,
    dry_run: bool = False,
    quiet: bool = False,
    ticker: str | None = None,
    strict_dividend_yield: bool = True,
) -> tuple[int, int, float, str]:
    """Add delta/IV/gamma to one ticker data + options JSON pair.

    Returns ``(ok, skipped, q, q_source)``; ``q_source`` records where the dividend
    yield came from so downstream consumers can tell whether the Greeks are
    trustworthy. Raises :class:`MissingDividendYieldError` for a known dividend payer
    with no resolvable yield, rather than enriching the whole chain at q = 0.
    """
    if not data_path.is_file():
        raise FileNotFoundError(f"Missing {data_path}")

    data = load_json(data_path)
    spot = data.get("current_price")
    if spot is None or not math.isfinite(float(spot)):
        raise ValueError(f"{data_path.name} has no valid current_price")
    S = float(spot)

    name = (ticker or _ticker_from_data_path(data_path)).lower()
    q, q_source = resolve_dividend_yield(
        name,
        data,
        S,
        output_dir=data_path.parent,
        override=div_yield,
        strict=strict_dividend_yield,
    )

    ts = data.get("timestamp") or datetime.now(timezone.utc).isoformat()
    valuation = _parse_valuation_datetime(str(ts))

    od = data.get("options_data")
    if not isinstance(od, dict):
        raise ValueError(f"{data_path.name} missing options_data")

    yc_path = yield_curve_path if yield_curve_path is not None else DEFAULT_OUTPUT_DIR / "yield_curve.json"
    flat_r = flat_risk_free
    curve: TreasuryZeroCurve | None = None
    curve_how: str | None = None
    if flat_r is None:
        curve, err_file = load_yield_curve_json(yc_path)
        if curve is not None:
            curve_how = f"{yc_path} (saved)"
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
        q=q,
        n_steps=tree_steps,
        log=not quiet,
    )
    if not quiet:
        print(f"Spot: {S:.4f}  valuation: {valuation.isoformat()}")
        if curve is not None:
            print(f"Treasury curve: {curve_how}  FRED as-of: {curve.as_of_date}")
            data["treasury_zero_curve"] = curve.to_json_dict()
        else:
            print(f"Flat risk-free (continuous): {fallback_rate:.6f}")
        print(f"Div yield: {q:.4f}  source: {q_source}  tree steps: {tree_steps}")
        print(f"Contracts with delta: {ok}  without / skipped: {skipped}")

    if dry_run:
        return ok, skipped, q, q_source

    # Stamp the yield actually used onto the chain so consumers can audit the Greeks.
    data["dividend_yield"] = q
    data["dividend_yield_source"] = q_source

    if curve is not None:
        data["treasury_zero_curve"] = curve.to_json_dict()

    save_json(data_path, data)
    if options_path.is_file():
        save_json(options_path, od)
    return ok, skipped, q, q_source


def _enrich_one_ticker(
    ticker: str,
    output_dir: Path,
    yc: Path,
    *,
    tree_steps: int,
    quiet: bool,
) -> tuple[str, int, int, float, str] | None:
    data_path = output_dir / f"{ticker}_data.json"
    if not data_path.is_file():
        return None
    options_path = output_dir / f"{ticker}_options.json"
    ok, skipped, q, q_source = enrich_options_files(
        data_path,
        options_path,
        yield_curve_path=yc,
        tree_steps=tree_steps,
        quiet=quiet,
        ticker=ticker,
    )
    return ticker, ok, skipped, q, q_source


def enrich_all_option_chains(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    tickers: tuple[str, ...] = ("mstr", "strc", "ibit"),
    yield_curve_path: Path | None = None,
    quiet: bool = True,
    tree_steps: int = DEFAULT_TREE_STEPS,
    parallel: bool = False,
    skip_tickers: frozenset[str] | set[str] | None = None,
) -> None:
    """Run delta/IV enrichment for each ticker whose data JSON exists."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    yc = yield_curve_path if yield_curve_path is not None else output_dir / "yield_curve.json"
    skip = frozenset(skip_tickers or ())
    skipped = [t for t in tickers if t in skip and (output_dir / f"{t}_data.json").is_file()]
    active = [
        t
        for t in tickers
        if t not in skip and (output_dir / f"{t}_data.json").is_file()
    ]
    if not active and not skipped:
        return

    print("\n" + "=" * 70)
    print("ENRICHING OPTIONS (delta / IV / gamma)")
    print("=" * 70)
    if skipped:
        print(f"Skipping {', '.join(t.upper() for t in skipped)} (cache hit, already enriched)")
    if not active:
        return

    failures: list[str] = []

    def report(result: tuple[str, int, int, float, str] | None) -> None:
        if result is None:
            return
        ticker, ok, skipped, q, q_source = result
        print(f"\n{ticker.upper()}:")
        print(f"   ✓ {ok} contracts enriched, {skipped} skipped")
        print(f"   ✓ Dividend yield q={q:.4%}  source: {q_source}")
        options_path = output_dir / f"{ticker}_options.json"
        if options_path.is_file():
            print(f"   ✓ Updated {ticker}_data.json, {options_path.name}")

    if parallel and len(active) > 1:
        print(f"Running {len(active)} legs in parallel...")
        with ThreadPoolExecutor(max_workers=len(active)) as pool:
            futures = {
                pool.submit(
                    _enrich_one_ticker,
                    ticker,
                    output_dir,
                    yc,
                    tree_steps=tree_steps,
                    quiet=quiet,
                ): ticker
                for ticker in active
            }
            for fut in as_completed(futures):
                try:
                    report(fut.result())
                except MissingDividendYieldError as exc:
                    failures.append(f"{futures[fut].upper()}: {exc}")
    else:
        for ticker in active:
            try:
                report(_enrich_one_ticker(ticker, output_dir, yc, tree_steps=tree_steps, quiet=quiet))
            except MissingDividendYieldError as exc:
                failures.append(f"{ticker.upper()}: {exc}")

    if failures:
        # Leave the chain unenriched rather than storing Greeks solved at q=0;
        # is_options_chain_enriched() then returns False and the next run retries.
        print("\n" + "!" * 70)
        print("DIVIDEND YIELD UNRESOLVED — CHAIN LEFT UNENRICHED (Greeks would be wrong)")
        print("!" * 70)
        for msg in failures:
            print(f"  ✗ {msg}")


def main() -> None:
    p = argparse.ArgumentParser(description="Add American binomial delta (from mid) to IBIT JSON.")
    p.add_argument("--ibit-data", type=Path, default=DEFAULT_OUTPUT_DIR / "ibit_data.json")
    p.add_argument("--ibit-options", type=Path, default=DEFAULT_OUTPUT_DIR / "ibit_options.json")
    p.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Alias for --ibit-data (e.g. output/mstr_data.json)",
    )
    p.add_argument(
        "--options",
        type=Path,
        default=None,
        help="Alias for --ibit-options (e.g. output/mstr_options.json)",
    )
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
    p.add_argument(
        "--div-yield",
        type=float,
        default=None,
        help=(
            "Continuous dividend yield on spot (default: dividend_yield in the data JSON, "
            "else <ticker>_dividend_rate×par/spot from the treasury JSONs)"
        ),
    )
    p.add_argument(
        "--allow-missing-dividend-yield",
        action="store_true",
        help="Warn and price at q=0 instead of erroring when a payer's yield is unresolvable",
    )
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
    if args.data is not None:
        args.ibit_data = args.data
    if args.options is not None:
        args.ibit_options = args.options

    flat_r = args.flat_risk_free
    if args.risk_free is not None and flat_r is None:
        flat_r = args.risk_free

    try:
        ok, skipped, q, q_source = enrich_options_files(
            args.ibit_data,
            args.ibit_options,
            yield_curve_path=args.yield_curve,
            flat_risk_free=flat_r,
            div_yield=args.div_yield,
            tree_steps=args.tree_steps,
            dry_run=args.dry_run,
            quiet=args.quiet,
            strict_dividend_yield=not args.allow_missing_dividend_yield,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"Contracts with delta: {ok}  without / skipped: {skipped}")
        print(f"Dividend yield q={q:.4%}  source: {q_source}")
    if not args.dry_run:
        print(f"Updated {args.ibit_data}")
        if args.ibit_options.is_file():
            print(f"Updated {args.ibit_options}")


if __name__ == "__main__":
    main()
