#!/usr/bin/env python3
"""Selling the STRC $100 call across expiries — daily dividends, early exercise, par ceiling.

Three things make a textbook covered-call read wrong for STRC:

1. **Discrete daily dividends.** From 1 Nov 2026 STRC declares a dividend for every
   calendar day (12.00% on the $100 stated amount, $1.00 a month, ~$0.033 a day), each
   payable the next business day (8-K of 15 Oct 2026). Under T+1 a weekend's record
   dates all go ex on Friday, so Friday carries ~$0.10 and the day before a bank holiday
   carries two days. A continuous yield cannot tell Thursday from Tuesday, so this
   module prices on the actual ex-date ladder.
2. **Early exercise.** The dividend (~12%/yr on spot) is roughly 3x the financing a call
   holder saves by paying the strike late (~4.2%). An in-the-money call is therefore
   exercised at the close before an ex-date once its remaining time value is below the
   dividend it would otherwise miss. Monthly options expire on a Friday, which is itself
   an ex-date, so an ITM call in expiry week is normally exercised on *Thursday* to collect
   Friday's three-day dividend.
3. **The ~$100 ceiling.** Strategy sells STRC through its ATM program at or above par and
   resets the rate monthly to hold it there; management says it will keep STRC at par,
   and the tape agrees (highest close since the July-2025 IPO: $100.07). A lognormal model
   puts real probability on STRC at $103; the issuer's supply does not. So the premium is
   read here as the price of the cap *breaking*, and we report the break probability each
   premium implies.

Pricing is a log-space implicit finite-difference solve of the American call with a jump
condition V(S, t_ex-) = V(S - D, t_ex+) at each ex-date and an exercise check at the close
before it. Quotes come from Cboe's delayed feed (Nasdaq as fallback), the declared
dividend ladder from Nasdaq, rates from the Treasury zero curve.

  python strc_call_writer.py                  # live chain, $100 calls, all expiries
  python strc_call_writer.py --strike 105     # another strike
  python strc_call_writer.py --rate 0.115     # project a different STRC rate after the declared month
"""

from __future__ import annotations

import argparse
import calendar as _calendar
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from scipy.linalg import solve_banded
from scipy.optimize import brentq

from strc_paths import OUTPUT_DIR, ensure_output_dirs

NY = ZoneInfo("America/New_York")
YEAR_SECONDS = 365.0 * 24 * 3600  # ACT/365 for vol and rates alike

STATED_AMOUNT = 100.0
DEFAULT_STRIKE = 100.0
DEFAULT_STRC_RATE = 0.12  # 12.00% held for Nov-2026 record dates (8-K 15 Oct 2026)
DEFAULT_RISK_FREE = 0.042

# Highest STRC close / intraday high since the July-2025 IPO, as of 3 Nov 2026 (Nasdaq
# history). Used only when history cannot be fetched; the live run recomputes them.
OBSERVED_MAX_CLOSE = 100.07
OBSERVED_MAX_HIGH = 100.4182

# Reg-T-style naked equity call margin: 20% of underlying less OTM amount, floor 10%.
NAKED_CALL_MARGIN_RATE = 0.20
NAKED_CALL_MARGIN_FLOOR = 0.10

# Where the cap breaks, how far above the strike might STRC settle? These are scenario
# sizes, not forecasts: the issuer can still cut the rate, and ATM supply returns.
CAP_BREAK_JUMPS = (0.5, 1.0, 2.0, 5.0)

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
NASDAQ_CHAIN_URL = (
    "https://api.nasdaq.com/api/quote/{ticker}/option-chain?assetclass=stocks&limit=1000"
    "&fromdate=all&todate=undefined&excode=oprac&callput=callput&money=all&type=all"
)
NASDAQ_DIVIDENDS_URL = "https://api.nasdaq.com/api/quote/{ticker}/dividends?assetclass=stocks"
NASDAQ_HISTORY_URL = (
    "https://api.nasdaq.com/api/quote/{ticker}/historical?assetclass=stocks"
    "&fromdate={start}&todate={end}&limit=9999"
)
# Nasdaq's API rejects non-browser user agents; this is a generic client string.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


# ---------------------------------------------------------------------------
# Market calendar: trading days (NYSE) and T+1 settlement days (NYSE ∪ Fed holidays)
# ---------------------------------------------------------------------------


def _holiday_calendars():
    from pandas.tseries.holiday import (
        AbstractHolidayCalendar,
        GoodFriday,
        Holiday,
        USColumbusDay,
        USLaborDay,
        USMartinLutherKingJr,
        USMemorialDay,
        USPresidentsDay,
        USThanksgivingDay,
        nearest_workday,
        sunday_to_monday,
    )

    class NYSEHolidays(AbstractHolidayCalendar):
        # NYSE closes the Friday before a Saturday holiday — except New Year's Day.
        rules = [
            Holiday("NewYearsDay", month=1, day=1, observance=sunday_to_monday),
            USMartinLutherKingJr,
            USPresidentsDay,
            GoodFriday,
            USMemorialDay,
            Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
            Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
            USLaborDay,
            USThanksgivingDay,
            Holiday("Christmas", month=12, day=25, observance=nearest_workday),
        ]

    class FedHolidays(AbstractHolidayCalendar):
        # Reserve Banks stay open the Friday before a Saturday holiday.
        rules = [
            Holiday("NewYearsDay", month=1, day=1, observance=sunday_to_monday),
            USMartinLutherKingJr,
            USPresidentsDay,
            USMemorialDay,
            Holiday("Juneteenth", month=6, day=19, start_date="2021-06-18", observance=sunday_to_monday),
            Holiday("IndependenceDay", month=7, day=4, observance=sunday_to_monday),
            USLaborDay,
            USColumbusDay,
            Holiday("VeteransDay", month=11, day=11, observance=sunday_to_monday),
            USThanksgivingDay,
            Holiday("Christmas", month=12, day=25, observance=sunday_to_monday),
        ]

    return NYSEHolidays(), FedHolidays()


class MarketCalendar:
    """NYSE trading days and DTC (T+1) settlement days over a date window."""

    def __init__(self, start: date, end: date):
        nyse_cal, fed_cal = _holiday_calendars()
        lo, hi = start - timedelta(days=30), end + timedelta(days=30)
        self.nyse_holidays = {d.date() for d in nyse_cal.holidays(lo, hi)}
        fed = {d.date() for d in fed_cal.holidays(lo, hi)}
        self.settlement_holidays = self.nyse_holidays | fed

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.nyse_holidays

    def is_settlement_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.settlement_holidays

    def prev_trading_day(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def settlement_date(self, trade_date: date) -> date:
        """T+1: the first settlement day strictly after the trade date."""
        d = trade_date + timedelta(days=1)
        while not self.is_settlement_day(d):
            d += timedelta(days=1)
        return d

    def ex_date(self, record_date: date) -> date:
        """First trading day whose T+1 settlement lands after the record date.

        A buyer on the ex-date (or later) settles too late to be holder of record. For a
        business-day record date this is the record date itself; a Saturday/Sunday record
        date goes ex on Friday; Veterans Day (NYSE open, settlement closed) goes ex the
        day before because that day's trades settle after the holiday.
        """
        t = record_date - timedelta(days=10)
        while True:
            if self.is_trading_day(t) and self.settlement_date(t) > record_date:
                return t
            t += timedelta(days=1)


# ---------------------------------------------------------------------------
# Dividend ladder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExDividend:
    ex_date: date
    amount: float
    record_dates: tuple[date, ...]
    declared: bool


def project_record_dividends(
    start: date,
    end: date,
    rate: float,
    *,
    par: float = STATED_AMOUNT,
) -> list[tuple[date, float]]:
    """(record_date, amount) for every calendar day in [start, end] at an annual ``rate`` on par.

    Each month's rate·par/12 is spread evenly over its days (the 8-K rounds each day to
    $0.03/$0.04 so the month sums to exactly $1.00 at 12%).
    """
    out: list[tuple[date, float]] = []
    d = start
    while d <= end:
        dim = _calendar.monthrange(d.year, d.month)[1]
        out.append((d, rate * par / 12.0 / dim))
        d += timedelta(days=1)
    return out


def build_ex_dividend_ladder(
    after: date,
    through: date,
    cal: MarketCalendar,
    *,
    rate: float = DEFAULT_STRC_RATE,
    declared: Sequence[dict[str, Any]] = (),
) -> list[ExDividend]:
    """Ex-dividend events with ex_date in (after, through].

    ``declared`` rows ({ex_date, record_date, amount}) are used as published; record
    dates after the last declared one are projected daily at ``rate``.
    """
    by_ex: dict[date, dict[str, Any]] = {}
    last_declared_record: date | None = None
    for row in declared:
        ex, rec, amt = row["ex_date"], row["record_date"], float(row["amount"])
        slot = by_ex.setdefault(ex, {"amount": 0.0, "records": [], "declared": True})
        slot["amount"] += amt
        slot["records"].append(rec)
        last_declared_record = rec if last_declared_record is None else max(last_declared_record, rec)

    proj_start = (last_declared_record + timedelta(days=1)) if last_declared_record else after
    # Record dates up to a week past ``through`` can still go ex on or before it.
    for rec, amt in project_record_dividends(proj_start, through + timedelta(days=7), rate):
        ex = cal.ex_date(rec)
        slot = by_ex.setdefault(ex, {"amount": 0.0, "records": [], "declared": False})
        slot["amount"] += amt
        slot["records"].append(rec)

    return [
        ExDividend(ex, slot["amount"], tuple(sorted(slot["records"])), slot["declared"])
        for ex, slot in sorted(by_ex.items())
        if after < ex <= through
    ]


# ---------------------------------------------------------------------------
# American call with discrete cash dividends — implicit FD in x = ln S
# ---------------------------------------------------------------------------


@dataclass
class PDEResult:
    price: float
    delta: float
    gamma: float
    # Spot at the close before each dividend above which exercising is optimal (inf: never).
    boundary: np.ndarray = field(default_factory=lambda: np.empty(0))


def american_call_discrete_dividends(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    div_times: Sequence[float] = (),
    div_amounts: Sequence[float] = (),
    *,
    steps_per_day: int = 4,
    dx_target: float = 5e-4,
    n_sd: float = 6.0,
) -> PDEResult:
    """American call; spot drops by D_i at t_i, exercise allowed at any time.

    ``div_times`` are the exercise-decision instants (the close before each ex-date), in
    years. Between dividends the solve is Black-Scholes in x = ln S, fully implicit.
    """
    if not (S > 0 and K > 0 and T > 0 and sigma > 0):
        raise ValueError("need S, K, T, sigma > 0")
    t_div = np.asarray(div_times, dtype=float)
    d_div = np.asarray(div_amounts, dtype=float)
    keep = (t_div > 0) & (t_div < T) & (d_div > 0)
    order = np.argsort(t_div[keep])
    t_div, d_div = t_div[keep][order], d_div[keep][order]

    # Grid wide enough for ±n_sd moves plus the cumulative dividend drop.
    sd = sigma * math.sqrt(T)
    drop = math.log(S / max(S - d_div.sum(), 0.05 * S))
    lo = math.log(S) - n_sd * sd - drop - 0.05
    hi = max(math.log(S), math.log(K)) + n_sd * sd + 0.05
    n = int(np.clip(math.ceil((hi - lo) / dx_target), 400, 8000))
    dx = (hi - lo) / n
    k0 = int(round((math.log(S) - lo) / dx))
    lo = math.log(S) - k0 * dx  # put S exactly on a node
    x = lo + dx * np.arange(n + 1)
    s = np.exp(x)
    exercise = s - K
    V = np.maximum(exercise, 0.0)

    a = 0.5 * sigma * sigma / (dx * dx)
    b = (r - 0.5 * sigma * sigma) / (2.0 * dx)

    def banded(dt: float) -> np.ndarray:
        ab = np.zeros((3, n + 1))
        ab[0, 2:] = -dt * (a + b)  # super-diagonal (row i -> V[i+1]) for i = 1..n-1
        ab[1, :] = 1.0 + dt * (2.0 * a + r)
        ab[1, 0] = ab[1, -1] = 1.0
        ab[2, :-2] = -dt * (a - b)  # sub-diagonal (row i -> V[i-1]) for i = 1..n-1
        return ab

    boundary = np.full(len(t_div), np.inf)
    knots = np.concatenate(([0.0], t_div, [T]))
    for seg in range(len(knots) - 1, 0, -1):
        t_lo, t_hi = knots[seg - 1], knots[seg]
        span = t_hi - t_lo
        if span > 0:
            m = max(1, math.ceil(span * 365.0 * steps_per_day))
            dt = span / m
            ab = banded(dt)
            for step in range(m):
                # Deep ITM edge: exercise now, or hold and pay K at expiry net of the
                # dividends still to come — whichever is worth more.
                t_now = t_hi - (step + 1) * dt
                ahead = t_div > t_now
                pvd = float(np.sum(d_div[ahead] * np.exp(-r * (t_div[ahead] - t_now))))
                V[0] = 0.0
                V[-1] = max(exercise[-1], s[-1] - pvd - K * math.exp(-r * (T - t_now)))
                V = solve_banded((1, 1), ab, V, check_finite=False)
                np.maximum(V, exercise, out=V)
        if seg - 1 >= 1:  # knot seg-1 is dividend index seg-2
            i = seg - 2
            shifted = s - d_div[i]
            xs = np.log(np.maximum(shifted, 1e-12))
            cont = np.interp(xs, x, V, left=0.0)
            cont[shifted <= 0] = 0.0
            gain = exercise - cont
            itm = np.flatnonzero((gain >= 0) & (exercise > 0))
            if itm.size:
                j = itm[0]
                if j > 0 and gain[j - 1] < 0:
                    w = -gain[j - 1] / (gain[j] - gain[j - 1])
                    boundary[i] = s[j - 1] + w * (s[j] - s[j - 1])
                else:
                    boundary[i] = s[j]
            V = np.maximum(cont, exercise)

    price = float(V[k0])
    s_m, s_0, s_p = s[k0 - 1], s[k0], s[k0 + 1]
    delta = float((V[k0 + 1] - V[k0 - 1]) / (s_p - s_m))
    gamma = float(
        2.0
        * ((V[k0 + 1] - V[k0]) / (s_p - s_0) - (V[k0] - V[k0 - 1]) / (s_0 - s_m))
        / (s_p - s_m)
    )
    return PDEResult(price=price, delta=delta, gamma=gamma, boundary=boundary)


def implied_vol(
    target: float,
    S: float,
    K: float,
    T: float,
    r: float,
    div_times: Sequence[float],
    div_amounts: Sequence[float],
    *,
    lo: float = 0.005,
    hi: float = 1.5,
    **pde_kw: Any,
) -> float | None:
    """σ such that the discrete-dividend American call prices at ``target``."""
    if not (target > 0 and math.isfinite(target)):
        return None

    def f(sig: float) -> float:
        return american_call_discrete_dividends(S, K, T, r, sig, div_times, div_amounts, **pde_kw).price - target

    f_lo, f_hi = f(lo), f(hi)
    if f_lo > 0 or f_hi < 0:
        return None  # below the σ→0 bound (≈ intrinsic) or absurdly rich
    return float(brentq(f, lo, hi, xtol=1e-5, rtol=1e-6, maxiter=60))


def simulate_early_exercise(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    div_times: Sequence[float],
    div_amounts: Sequence[float],
    boundary: Sequence[float],
    *,
    n_paths: int = 20_000,
    seed: int = 7,
) -> dict[str, Any]:
    """Risk-neutral GBM between ex-dates: how often the holder exercises before expiry.

    At each decision close the path is exercised if spot is at/above the PDE boundary;
    otherwise spot drops by the dividend. Returns P(early), P(ITM at expiry) and the
    distribution of the exercise index.
    """
    rng = np.random.default_rng(seed)
    t_div = np.asarray(div_times, dtype=float)
    d_div = np.asarray(div_amounts, dtype=float)
    bnd = np.asarray(boundary, dtype=float)
    spot = np.full(n_paths, float(S))
    alive = np.ones(n_paths, dtype=bool)
    exercised_at = np.full(n_paths, -1, dtype=int)
    t_prev = 0.0
    for i, (t_i, d_i, b_i) in enumerate(zip(t_div, d_div, bnd)):
        dt = max(t_i - t_prev, 0.0)
        if dt > 0:
            z = rng.standard_normal(n_paths)
            spot *= np.exp((r - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z)
        hit = alive & (spot >= b_i)
        exercised_at[hit] = i
        alive &= ~hit
        spot = np.maximum(spot - d_i, 1e-9)
        t_prev = t_i
    dt = max(T - t_prev, 0.0)
    if dt > 0:
        z = rng.standard_normal(n_paths)
        spot *= np.exp((r - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z)
    itm_at_expiry = alive & (spot > K)
    return {
        "p_early_exercise": float((exercised_at >= 0).mean()),
        "p_itm_at_expiry_if_not_early": float(itm_at_expiry.mean()),
        "p_assigned_total": float((exercised_at >= 0).mean() + itm_at_expiry.mean()),
        "exercise_index_counts": np.bincount(exercised_at[exercised_at >= 0], minlength=len(t_div)).tolist(),
    }


# ---------------------------------------------------------------------------
# The par ceiling
# ---------------------------------------------------------------------------


def implied_cap_break_probability(premium: float, cap_value: float, jump: float) -> float | None:
    """P(break) such that premium = cap_value + P(break)·jump (call pays ~jump if the cap breaks).

    Returns None when even a certain break would not justify the premium.
    """
    if jump <= 0:
        raise ValueError("jump must be positive")
    p = (premium - cap_value) / jump
    if p > 1.0:
        return None
    return max(p, 0.0)


def annual_equivalent_probability(p: float, years: float) -> float:
    """Per-year probability that compounds to ``p`` over ``years``: 1 − (1 − p)^(1/years)."""
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return 1.0 - (1.0 - p) ** (1.0 / years)


def naked_call_margin(spot: float, strike: float, premium: float) -> float:
    otm = max(strike - spot, 0.0)
    return max(NAKED_CALL_MARGIN_RATE * spot - otm, NAKED_CALL_MARGIN_FLOOR * spot) + premium


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def _http_json(url: str) -> Any:
    import requests

    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _cached(key: str, url: str, force_refresh: bool, ttl: int = 900) -> Any:
    from data_cache import get_or_fetch

    return get_or_fetch(key, lambda: _http_json(url), ttl=ttl, force_refresh=force_refresh)


def parse_occ_symbol(symbol: str) -> tuple[str, date, str, float]:
    """'STRC261120C00100000' -> ('STRC', 2026-11-20, 'C', 100.0)."""
    tail = symbol[-15:]
    root = symbol[:-15].strip()
    exp = datetime.strptime(tail[:6], "%y%m%d").date()
    return root, exp, tail[6], int(tail[7:]) / 1000.0


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(str(v).replace("$", "").replace(",", ""))
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def load_chain(ticker: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """Underlying quote + every contract. Cboe delayed feed first, Nasdaq second."""
    errors: list[str] = []
    try:
        raw = _cached(f"cboe_options_{ticker}", CBOE_URL.format(ticker=ticker), force_refresh)
        und = raw["data"]
        ts = datetime.strptime(raw["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        contracts = []
        for o in und["options"]:
            _, exp, cp, k = parse_occ_symbol(o["option"])
            contracts.append(
                {
                    "expiry": exp,
                    "type": cp,
                    "strike": k,
                    "bid": _num(o.get("bid")),
                    "ask": _num(o.get("ask")),
                    "last": _num(o.get("last_trade_price")),
                    "open_interest": _num(o.get("open_interest")),
                    "volume": _num(o.get("volume")),
                    "vendor_iv": _num(o.get("iv")),
                }
            )
        bid, ask = _num(und.get("bid")), _num(und.get("ask"))
        spot = 0.5 * (bid + ask) if bid and ask else _num(und.get("current_price"))
        return {
            "source": "cboe-delayed",
            "as_of": ts,
            "spot": spot,
            "spot_bid": bid,
            "spot_ask": ask,
            "iv30": (_num(und.get("iv30")) or 0.0) / 100.0,
            "contracts": contracts,
        }
    except Exception as exc:  # noqa: BLE001 — fall through to Nasdaq, report both if it fails
        errors.append(f"cboe: {exc}")

    try:
        raw = _cached(f"nasdaq_options_{ticker}", NASDAQ_CHAIN_URL.format(ticker=ticker), force_refresh)
        d = raw["data"]
        contracts = []
        group: date | None = None
        for row in d["table"]["rows"]:
            if row.get("expirygroup"):
                group = datetime.strptime(row["expirygroup"], "%B %d, %Y").date()
                continue
            if group is None or row.get("strike") is None:
                continue
            for cp, pre in (("C", "c_"), ("P", "p_")):
                contracts.append(
                    {
                        "expiry": group,
                        "type": cp,
                        "strike": _num(row["strike"]),
                        "bid": _num(row.get(pre + "Bid")),
                        "ask": _num(row.get(pre + "Ask")),
                        "last": _num(row.get(pre + "Last")),
                        "open_interest": _num(row.get(pre + "Openinterest")),
                        "volume": _num(row.get(pre + "Volume")),
                        "vendor_iv": None,
                    }
                )
        last = _num(str(d.get("lastTrade", "")).split("$")[-1].split(" ")[0])
        return {
            "source": "nasdaq",
            "as_of": datetime.now(timezone.utc),
            "spot": last,
            "spot_bid": None,
            "spot_ask": None,
            "iv30": None,
            "contracts": contracts,
        }
    except Exception as exc:  # noqa: BLE001
        errors.append(f"nasdaq: {exc}")
    raise RuntimeError("no option chain for {}: {}".format(ticker, "; ".join(errors)))


def load_declared_dividends(ticker: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
    raw = _cached(f"nasdaq_dividends_{ticker}", NASDAQ_DIVIDENDS_URL.format(ticker=ticker), force_refresh, ttl=6 * 3600)
    out = []
    for row in raw["data"]["dividends"]["rows"]:
        try:
            out.append(
                {
                    "ex_date": datetime.strptime(row["exOrEffDate"], "%m/%d/%Y").date(),
                    "record_date": datetime.strptime(row["recordDate"], "%m/%d/%Y").date(),
                    "pay_date": datetime.strptime(row["paymentDate"], "%m/%d/%Y").date(),
                    "amount": _num(row["amount"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return [r for r in out if r["amount"] is not None]


def load_price_history(ticker: str, start: date, end: date, *, force_refresh: bool = False) -> list[dict[str, Any]]:
    url = NASDAQ_HISTORY_URL.format(ticker=ticker, start=start.isoformat(), end=end.isoformat())
    raw = _cached(f"nasdaq_history_{ticker}", url, force_refresh, ttl=6 * 3600)
    rows = []
    for row in raw["data"]["tradesTable"]["rows"]:
        rows.append(
            {
                "date": datetime.strptime(row["date"], "%m/%d/%Y").date(),
                "close": _num(row["close"]),
                "high": _num(row["high"]),
            }
        )
    return sorted((r for r in rows if r["close"] is not None), key=lambda r: r["date"])


def ceiling_stats(history: Sequence[dict[str, Any]], strike: float, since: date | None = None) -> dict[str, Any]:
    rows = [h for h in history if since is None or h["date"] >= since]
    closes = np.array([h["close"] for h in rows], dtype=float)
    highs = np.array([h["high"] if h["high"] is not None else h["close"] for h in rows], dtype=float)
    if closes.size == 0:
        return {"sessions": 0}
    overshoot = np.maximum(closes - strike, 0.0)
    return {
        "since": rows[0]["date"].isoformat(),
        "sessions": int(closes.size),
        "max_close": float(closes.max()),
        "max_high": float(highs.max()),
        "share_close_at_or_above_strike": float((closes >= strike).mean()),
        "mean_close_overshoot": float(overshoot.mean()),
        "max_close_overshoot": float(overshoot.max()),
    }


def share_of_closes_at_or_above(history: Sequence[dict[str, Any]], level: float) -> float:
    closes = np.array([h["close"] for h in history], dtype=float)
    return float((closes >= level).mean()) if closes.size else float("nan")


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _decision_time_years(cal: MarketCalendar, ex: date, valuation: datetime) -> float:
    """Years from valuation to the close before ``ex`` — the last chance to exercise for it."""
    prev = cal.prev_trading_day(ex)
    close_dt = datetime.combine(prev, time(16, 0), tzinfo=NY)
    return max((close_dt - valuation).total_seconds() / YEAR_SECONDS, 1e-6)


def _expiry_time_years(expiry: date, valuation: datetime) -> float:
    close_dt = datetime.combine(expiry, time(16, 0), tzinfo=NY)
    return max((close_dt - valuation).total_seconds() / YEAR_SECONDS, 1.0 / (365 * 24))


def _rate_for(curve: Any, T: float) -> float:
    if curve is not None:
        r = curve.equivalent_constant_rate(T)
        if math.isfinite(r):
            return float(r)
    return DEFAULT_RISK_FREE


def expiry_week_boundary(
    expiry: date,
    strike: float,
    sigma: float,
    r: float,
    cal: MarketCalendar,
    ladder: Sequence[ExDividend],
    *,
    trading_days: int = 5,
) -> float | None:
    """Thursday-of-expiry-week exercise boundary for an option priced at ``sigma``.

    Every expiry ends up as a front-month in its last week, so this uses front-month vol
    rather than the long-dated IV that set today's premium.
    """
    start = expiry
    for _ in range(trading_days):
        start = cal.prev_trading_day(start)
    valuation = datetime.combine(start, time(16, 0), tzinfo=NY)
    evs = [e for e in ladder if start < e.ex_date <= expiry]
    if not evs:
        return None
    res = american_call_discrete_dividends(
        strike,
        strike,
        _expiry_time_years(expiry, valuation),
        r,
        sigma,
        [_decision_time_years(cal, e.ex_date, valuation) for e in evs],
        [e.amount for e in evs],
    )
    b = float(res.boundary[-1])
    return b if math.isfinite(b) else None


@dataclass
class ExpiryAnalysis:
    expiry: str
    days: int
    bid: float | None
    ask: float | None
    mid: float | None
    open_interest: float | None
    risk_free: float
    n_ex_dates: int
    dividends_to_expiry: float
    dividends_to_thursday: float
    last_ex_dividend: float
    iv_mid: float | None
    iv_bid: float | None
    vendor_iv: float | None
    delta: float | None
    premium_yield_annual_bid: float | None
    premium_per_day_bid: float | None
    covered_unchanged_annual: float | None
    covered_called_thursday_annual: float | None
    stock_only_annual: float
    first_exercisable_under_cap: str | None
    business_days_exercisable_under_cap: int
    boundary_first_ex: float | None
    boundary_30d_before: float | None
    boundary_5d_before: float | None
    boundary_last_ex: float | None
    p_early_exercise_rn: float | None
    p_assigned_rn: float | None
    hist_share_closes_above_last_boundary: float | None
    cap_value: float
    implied_break_prob: dict[str, float | None]
    implied_break_prob_per_year: dict[str, float | None]
    naked_margin: float | None
    naked_return_on_margin_annual: float | None
    boundary_last_ex_front_iv: float | None
    hist_share_closes_above_front_boundary: float | None
    boundaries: list[dict[str, Any]] = field(default_factory=list)


def analyze_expiry(
    expiry: date,
    quote: dict[str, Any],
    *,
    spot: float,
    strike: float,
    valuation: datetime,
    cal: MarketCalendar,
    ladder: Sequence[ExDividend],
    curve: Any,
    history: Sequence[dict[str, Any]],
    cap_level: float,
    cap_value: float,
    front_iv: float | None = None,
    mc_paths: int = 20_000,
) -> ExpiryAnalysis:
    T = _expiry_time_years(expiry, valuation)
    days = (expiry - valuation.astimezone(NY).date()).days
    r = _rate_for(curve, T)

    evs = [e for e in ladder if e.ex_date <= expiry]
    t_div = [_decision_time_years(cal, e.ex_date, valuation) for e in evs]
    d_div = [e.amount for e in evs]
    div_total = float(sum(d_div))
    last_ex_div = d_div[-1] if evs and evs[-1].ex_date == expiry else 0.0
    div_to_thu = div_total - last_ex_div

    bid, ask = quote.get("bid"), quote.get("ask")
    bid = bid if bid and bid > 0 else None
    ask = ask if ask and ask > 0 else None
    mid = 0.5 * (bid + ask) if bid and ask else (ask / 2.0 if ask else None)

    iv_mid = implied_vol(mid, spot, strike, T, r, t_div, d_div) if mid else None
    iv_bid = implied_vol(bid, spot, strike, T, r, t_div, d_div) if bid else None
    sigma = iv_mid or iv_bid or quote.get("vendor_iv") or 0.08

    res = american_call_discrete_dividends(spot, strike, T, r, sigma, t_div, d_div)
    bnd = res.boundary

    front_bnd = expiry_week_boundary(expiry, strike, front_iv or sigma, r, cal, ladder)

    def _b(idx: int) -> float | None:
        if not len(bnd) or idx < 0:
            return None
        v = float(bnd[idx])
        return v if math.isfinite(v) else None

    def _idx_days_before(n_days: int) -> int:
        cutoff = expiry - timedelta(days=n_days)
        idx = [i for i, e in enumerate(evs) if e.ex_date <= cutoff]
        return idx[-1] if idx else -1

    reachable = [i for i, b in enumerate(bnd) if math.isfinite(b) and b <= cap_level]
    # Report the assignment day (the close before the ex-date), not the ex-date itself.
    first_reachable = cal.prev_trading_day(evs[reachable[0]].ex_date).isoformat() if reachable else None

    mc = simulate_early_exercise(spot, strike, T, r, sigma, t_div, d_div, bnd, n_paths=mc_paths) if evs else None

    years = max(days, 1) / 365.0
    prem = bid
    cov_unch = (prem + div_total) / spot / years if prem is not None else None
    cov_thu = (prem + div_to_thu + (strike - spot)) / spot / years if prem is not None else None

    jumps = {f"jump_{j:g}": implied_cap_break_probability(prem, cap_value, j) if prem else None for j in CAP_BREAK_JUMPS}
    per_year = {
        k: (annual_equivalent_probability(p, T) if p is not None else None) for k, p in jumps.items()
    }

    margin = naked_call_margin(spot, strike, prem) if prem else None
    rom = prem / margin / years if prem and margin else None

    return ExpiryAnalysis(
        expiry=expiry.isoformat(),
        days=days,
        bid=bid,
        ask=ask,
        mid=mid,
        open_interest=quote.get("open_interest"),
        risk_free=r,
        n_ex_dates=len(evs),
        dividends_to_expiry=div_total,
        dividends_to_thursday=div_to_thu,
        last_ex_dividend=last_ex_div,
        iv_mid=iv_mid,
        iv_bid=iv_bid,
        vendor_iv=quote.get("vendor_iv"),
        delta=res.delta,
        premium_yield_annual_bid=(prem / spot / years) if prem else None,
        premium_per_day_bid=(prem / max(days, 1)) if prem else None,
        covered_unchanged_annual=cov_unch,
        covered_called_thursday_annual=cov_thu,
        stock_only_annual=div_total / spot / years,
        first_exercisable_under_cap=first_reachable,
        business_days_exercisable_under_cap=len(reachable),
        boundary_first_ex=_b(0),
        boundary_30d_before=_b(_idx_days_before(30)),
        boundary_5d_before=_b(_idx_days_before(5)),
        boundary_last_ex=_b(len(bnd) - 1),
        p_early_exercise_rn=mc["p_early_exercise"] if mc else None,
        p_assigned_rn=mc["p_assigned_total"] if mc else None,
        hist_share_closes_above_last_boundary=(
            share_of_closes_at_or_above(history, float(bnd[-1])) if len(bnd) and math.isfinite(bnd[-1]) else None
        ),
        cap_value=cap_value,
        implied_break_prob=jumps,
        implied_break_prob_per_year=per_year,
        naked_margin=margin,
        naked_return_on_margin_annual=rom,
        boundary_last_ex_front_iv=front_bnd,
        hist_share_closes_above_front_boundary=(
            share_of_closes_at_or_above(history, front_bnd) if front_bnd is not None and history else None
        ),
        boundaries=[
            {
                "ex_date": e.ex_date.isoformat(),
                "exercise_by_close_of": cal.prev_trading_day(e.ex_date).isoformat(),
                "dividend": e.amount,
                "boundary": (float(b) if math.isfinite(b) else None),
            }
            for e, b in zip(evs, bnd)
        ],
    )


def run(
    *,
    ticker: str = "STRC",
    strike: float = DEFAULT_STRIKE,
    rate: float = DEFAULT_STRC_RATE,
    force_refresh: bool = False,
    mc_paths: int = 20_000,
) -> dict[str, Any]:
    from preferred_valuation import live_yield_curve

    chain = load_chain(ticker, force_refresh=force_refresh)
    valuation: datetime = chain["as_of"]
    spot = float(chain["spot"])
    today = valuation.astimezone(NY).date()

    calls = {
        c["expiry"]: c
        for c in chain["contracts"]
        if c["type"] == "C" and c["strike"] is not None and abs(c["strike"] - strike) < 1e-6
    }
    expiries = sorted(e for e in calls if e >= today)
    if not expiries:
        raise RuntimeError(f"no {ticker} ${strike:g} calls in the chain")

    cal = MarketCalendar(today, expiries[-1])
    try:
        declared_rows = load_declared_dividends(ticker, force_refresh=force_refresh)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ declared dividends unavailable ({exc}); projecting all at {rate:.2%}", file=sys.stderr)
        declared_rows = []
    declared = [r for r in declared_rows if r["ex_date"] > today]
    ladder = build_ex_dividend_ladder(today, expiries[-1], cal, rate=rate, declared=declared)

    try:
        history = load_price_history(ticker, date(2025, 7, 1), today, force_refresh=force_refresh)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ price history unavailable ({exc}); using recorded ceiling stats", file=sys.stderr)
        history = []
    stats_all = ceiling_stats(history, strike) if history else {
        "sessions": 0, "max_close": OBSERVED_MAX_CLOSE, "max_high": OBSERVED_MAX_HIGH,
        "mean_close_overshoot": 0.0, "max_close_overshoot": max(OBSERVED_MAX_CLOSE - strike, 0.0),
    }
    stats_recent = ceiling_stats(history, strike, since=today - timedelta(days=182)) if history else {}
    cap_level = float(stats_all["max_close"])
    # Fair value of the call if the cap simply holds: the largest close overshoot seen.
    # (Mean overshoot is ~$0.00x; the max is the conservative read.)
    cap_value = float(stats_all["max_close_overshoot"])

    curve = live_yield_curve(OUTPUT_DIR)
    # Front-month vol: what every expiry looks like in its final week.
    front_iv = None
    for e in expiries:
        q = calls[e]
        if (e - today).days > 60:
            break
        b, a = q.get("bid") or 0.0, q.get("ask") or 0.0
        mid = 0.5 * (b + a) if b > 0 and a > 0 else (a / 2.0 if a > 0 else None)
        if mid:
            T_e = _expiry_time_years(e, valuation)
            evs = [x for x in ladder if x.ex_date <= e]
            front_iv = implied_vol(
                mid, spot, strike, T_e, _rate_for(curve, T_e),
                [_decision_time_years(cal, x.ex_date, valuation) for x in evs], [x.amount for x in evs],
            )
            if front_iv:
                break
    front_iv = front_iv or chain.get("iv30") or None

    results = [
        analyze_expiry(
            e,
            calls[e],
            spot=spot,
            strike=strike,
            valuation=valuation,
            cal=cal,
            ladder=ladder,
            curve=curve,
            history=history,
            cap_level=cap_level,
            cap_value=cap_value,
            front_iv=front_iv,
            mc_paths=mc_paths,
        )
        for e in expiries
    ]

    next_ex = ladder[:10]
    return {
        "ticker": ticker,
        "strike": strike,
        "as_of": valuation.isoformat(),
        "chain_source": chain["source"],
        "spot": spot,
        "spot_bid": chain.get("spot_bid"),
        "spot_ask": chain.get("spot_ask"),
        "iv30": chain.get("iv30"),
        "front_iv": front_iv,
        "strc_rate_assumed": rate,
        "curve_as_of": getattr(curve, "as_of_date", None),
        "dividend_ladder_head": [
            {"ex_date": e.ex_date.isoformat(), "amount": round(e.amount, 6), "record_dates": [d.isoformat() for d in e.record_dates], "declared": e.declared}
            for e in next_ex
        ],
        "ceiling": {"all": stats_all, "last_6m": stats_recent, "cap_level_used": cap_level, "cap_value_used": cap_value},
        "expiries": [asdict(x) for x in results],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _fmt(v: Any, spec: str, na: str = "—") -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return na
    return format(v, spec)


def print_report(out: dict[str, Any]) -> None:
    k = out["strike"]
    print("=" * 100)
    as_of = datetime.fromisoformat(out["as_of"]).astimezone(NY).strftime("%Y-%m-%d %H:%M ET")
    print(f"{out['ticker']} ${k:g} CALL — SELLER'S VIEW   spot ${out['spot']:.2f}   "
          f"quotes {out['chain_source']} as of {as_of}")
    print(f"STRC rate assumed {out['strc_rate_assumed']:.2%} on $100 (daily record dates); "
          f"Treasury curve {out['curve_as_of']}")
    c = out["ceiling"]["all"]
    print(f"Ceiling: {c.get('sessions', 0)} sessions since IPO — max close ${c['max_close']:.2f}, "
          f"max high ${c['max_high']:.2f}, closes ≥ ${k:g}: {100 * c.get('share_close_at_or_above_strike', 0):.1f}%")
    print("=" * 100)

    print("\nNext ex-dates (exercise at the prior close to collect):")
    for e in out["dividend_ladder_head"]:
        tag = "declared" if e["declared"] else "projected"
        ex = date.fromisoformat(e["ex_date"])
        print(f"  {ex:%a %Y-%m-%d}  ${e['amount']:.4f}  ({tag})")

    rows = out["expiries"]
    print("\nPremium and carry (sell at the bid, per share):")
    print(f"{'expiry':<11}{'days':>5}{'bid':>7}{'ask':>7}{'OI':>7}{'IVmid':>8}{'Δ':>7}"
          f"{'prem/yr':>9}{'divs':>7}{'unch/yr':>9}{'called/yr':>10}{'stock/yr':>9}")
    for x in rows:
        print(
            f"{x['expiry']:<11}{x['days']:>5}{_fmt(x['bid'], '.2f'):>7}{_fmt(x['ask'], '.2f'):>7}"
            f"{_fmt(x['open_interest'], '.0f'):>7}{_fmt(x['iv_mid'] and 100 * x['iv_mid'], '.1f'):>8}"
            f"{_fmt(x['delta'], '.2f'):>7}"
            f"{_fmt(x['premium_yield_annual_bid'] and 100 * x['premium_yield_annual_bid'], '.2f'):>9}"
            f"{x['dividends_to_expiry']:>7.2f}"
            f"{_fmt(x['covered_unchanged_annual'] and 100 * x['covered_unchanged_annual'], '.2f'):>9}"
            f"{_fmt(x['covered_called_thursday_annual'] and 100 * x['covered_called_thursday_annual'], '.2f'):>10}"
            f"{100 * x['stock_only_annual']:>9.2f}"
        )

    cap = out["ceiling"]["cap_level_used"]
    print(f"\nEarly exercise — S* is the close (before an ex-date) at/above which the holder exercises."
          f"\n  own IV: the expiry's market IV;  Thu@front: expiry-week Thursday at front-month IV "
          f"{_fmt(out.get('front_iv') and 100 * out['front_iv'], '.1f')}%;  cap ${cap:.2f} = highest close")
    print(f"{'expiry':<11}{'S*now':>8}{'S*-30d':>8}{'S*-5d':>8}{'S*Thu':>8}{'Thu@front':>10}"
          f"{'1st day≤cap':>13}{'P(early)':>9}{'P(asgn)':>8}{'hist≥Thu@front':>15}")
    for x in rows:
        print(
            f"{x['expiry']:<11}{_fmt(x['boundary_first_ex'], '.2f'):>8}{_fmt(x['boundary_30d_before'], '.2f'):>8}"
            f"{_fmt(x['boundary_5d_before'], '.2f'):>8}{_fmt(x['boundary_last_ex'], '.2f'):>8}"
            f"{_fmt(x['boundary_last_ex_front_iv'], '.2f'):>10}"
            f"{(x['first_exercisable_under_cap'] or 'never'):>13}"
            f"{_fmt(x['p_early_exercise_rn'] and 100 * x['p_early_exercise_rn'], '.1f'):>9}"
            f"{_fmt(x['p_assigned_rn'] and 100 * x['p_assigned_rn'], '.1f'):>8}"
            f"{_fmt(x['hist_share_closes_above_front_boundary'] and 100 * x['hist_share_closes_above_front_boundary'], '.1f'):>15}"
        )
    print("  P(early)/P(asgn): risk-neutral lognormal at own IV — i.e. what the market's own pricing implies with NO cap.")

    print(f"\nCap-break probability the bid implies — by expiry (per-year equivalent). Cap value "
          f"${out['ceiling']['cap_value_used']:.2f}; the call pays ~$J if STRC escapes the ceiling:")
    hdr = "".join(f"{'J=$' + format(j, 'g'):>12}" for j in CAP_BREAK_JUMPS)
    print(f"{'expiry':<11}{hdr}{'naked RoM/yr':>14}")
    for x in rows:
        cells = ""
        for j in CAP_BREAK_JUMPS:
            p = x["implied_break_prob"][f"jump_{j:g}"]
            h = x["implied_break_prob_per_year"][f"jump_{j:g}"]
            cells += f"{(_fmt(p and 100 * p, '.0f') + '% (' + _fmt(h and 100 * h, '.0f') + '%/y)') if p is not None else '>100%':>12}"
        print(f"{x['expiry']:<11}{cells}{_fmt(x['naked_return_on_margin_annual'] and 100 * x['naked_return_on_margin_annual'], '.2f'):>14}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ticker", default="STRC")
    p.add_argument("--strike", type=float, default=DEFAULT_STRIKE)
    p.add_argument("--rate", type=float, default=DEFAULT_STRC_RATE,
                   help="STRC annual rate on $100 for record dates after the declared month")
    p.add_argument("--mc-paths", type=int, default=20_000)
    p.add_argument("--force-refresh", action="store_true")
    p.add_argument("--output", type=Path, default=OUTPUT_DIR / "strc_call_writer.json")
    args = p.parse_args()

    ensure_output_dirs()
    out = run(ticker=args.ticker.upper(), strike=args.strike, rate=args.rate,
              force_refresh=args.force_refresh, mc_paths=args.mc_paths)
    print_report(out)
    args.output.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
