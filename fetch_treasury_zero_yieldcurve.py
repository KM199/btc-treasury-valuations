"""
Bootstrap a Treasury zero-coupon (discount) curve from FRED constant-maturity par yields.

FRED series DGS* are nominal constant-maturity Treasury yields (par-style quotes), not
quoted STRIPS zero rates. We:

  1) Treat the 1mo / 3mo / 6mo points as simple money-market proxies: D(T)=exp(-y*T)
     with y the FRED value in decimal (see module docstring caveat).
  2) For maturities >= 1y, bootstrap semiannual par bonds sequentially, discounting
     interim coupons with log-linear interpolation of discount factors on already
     solved pillars plus the maturity being solved.

For option pricing with a single constant r over [0,T], we use the equivalent rate
  r_eq(T) = -ln(D(T)) / T
so that exp(-r_eq * T) matches the bootstrapped discount D(T).
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import requests
from scipy.optimize import brentq

FREDGRAPH_URL = (
    "https://fred.stlouisfed.org/graph/fredgraph.csv"
    "?id=DGS1MO,DGS3MO,DGS6MO,DGS1,DGS2,DGS3,DGS5,DGS7,DGS10,DGS20,DGS30"
)

# FRED column order must match URL id= order
FRED_CM_TENORS_YEARS: tuple[float, ...] = (
    1.0 / 12.0,
    0.25,
    0.5,
    1.0,
    2.0,
    3.0,
    5.0,
    7.0,
    10.0,
    20.0,
    30.0,
)

# Pillars used only for semiannual coupon bootstrap (>= 1y)
COUPON_BOOTSTRAP_TENORS: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0)


@dataclass
class TreasuryZeroCurve:
    """Bootstrapped discount curve D(T); use equivalent_constant_rate(T) for BS tree."""

    as_of_date: str
    par_yields_decimal: dict[str, float]  # e.g. {"DGS10": 0.0446, ...}
    pillar_times: list[float] = field(default_factory=list)
    log_discounts: list[float] = field(default_factory=list)

    def discount(self, T: float) -> float:
        if T <= 0:
            return 1.0
        ts = np.asarray(self.pillar_times, dtype=float)
        ld = np.asarray(self.log_discounts, dtype=float)
        return math.exp(_log_discount_interp_segments(T, ts, ld))

    def equivalent_constant_rate(self, T: float) -> float:
        """Continuous r with exp(-rT)=D(T) (matches tree using flat r over horizon)."""
        if T <= 0:
            return 0.0
        d = self.discount(T)
        if d <= 0 or d > 1.0:
            return float("nan")
        return -math.log(d) / T

    def _log_discount(self, t: float) -> float:
        ts = np.asarray(self.pillar_times, dtype=float)
        ld = np.asarray(self.log_discounts, dtype=float)
        return _log_discount_interp_segments(t, ts, ld)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source": "FRED DGS* (fredgraph.csv) + semiannual par bootstrap",
            "as_of_date": self.as_of_date,
            "par_yields_decimal": dict(self.par_yields_decimal),
            "pillars_years": list(self.pillar_times),
            "discount_factors": [math.exp(x) for x in self.log_discounts],
            "note": (
                "DGS are constant-maturity par-style yields, not STRIPS zeros; "
                "short-end uses exp(-y*T) proxy. r_eq(T)=-ln(D)/T for the binomial."
            ),
        }

    @classmethod
    def from_saved_dict(cls, data: dict[str, Any]) -> TreasuryZeroCurve:
        """Rebuild curve from `yield_curve.json` / `to_json_dict()` payload (ignores extra keys)."""
        skip = {"timestamp", "saved_at", "source", "note"}
        d = {k: v for k, v in data.items() if k not in skip}
        pillars = d.get("pillars_years")
        dfs = d.get("discount_factors")
        if not isinstance(pillars, list) or not isinstance(dfs, list) or len(pillars) != len(dfs):
            raise ValueError("yield curve JSON missing pillars_years/discount_factors")
        logd = [math.log(float(x)) for x in dfs]
        par = d.get("par_yields_decimal") or {}
        if not isinstance(par, dict):
            par = {}
        as_of = str(d.get("as_of_date") or "")
        return cls(
            as_of_date=as_of,
            par_yields_decimal={str(k): float(v) for k, v in par.items()},
            pillar_times=[float(x) for x in pillars],
            log_discounts=logd,
        )


def _parse_fredgraph_csv(text: str) -> tuple[str, dict[str, float]]:
    """Return (record_date_iso, {series_id: yield_decimal}) from last complete row."""
    f = io.StringIO(text)
    reader = csv.reader(f)
    header = next(reader)
    if not header:
        raise ValueError("Empty FRED CSV")
    h0 = header[0].strip().lower()
    if h0 not in ("date", "observation_date"):
        raise ValueError(f"Unexpected FRED CSV header: {header[0]!r}")
    series_ids = [h.strip() for h in header[1:]]
    last_good: dict[str, float] | None = None
    last_date = ""
    for row in reader:
        if not row or len(row) < 2:
            continue
        d = row[0].strip()
        vals: dict[str, float] = {}
        ok = True
        for sid, cell in zip(series_ids, row[1:]):
            cell = cell.strip()
            if not cell or cell == ".":
                ok = False
                break
            try:
                vals[sid] = float(cell) / 100.0
            except ValueError:
                ok = False
                break
        if ok:
            last_good = vals
            last_date = d
    if last_good is None:
        raise ValueError("No complete FRED yield row found")
    return last_date, last_good


def fetch_fred_cm_yields(session: requests.Session | None = None) -> tuple[str, dict[str, float]]:
    sess = session or requests.Session()
    r = sess.get(FREDGRAPH_URL, timeout=30)
    r.raise_for_status()
    return _parse_fredgraph_csv(r.text)


def _coupon_payment_times(T_mat: float) -> list[float]:
    n = int(round(2.0 * T_mat))
    if abs(n - 2.0 * T_mat) > 1e-6:
        raise ValueError(f"Maturity {T_mat} is not a multiple of 0.5y for coupon grid")
    return [0.5 * k for k in range(1, n + 1)]


def _log_discount_interp_segments(t: float, ts: np.ndarray, ld: np.ndarray) -> float:
    """Log-linear discount interpolation on sorted pillars; flat extrapolation outside."""
    if ts.size == 0:
        return 0.0
    if t <= float(ts[0]):
        if float(ts[0]) <= 0:
            return float(ld[0])
        return float(ld[0] * (t / float(ts[0])))
    if t >= float(ts[-1]):
        if ts.size == 1:
            return float(ld[0])
        slope = (float(ld[-1]) - float(ld[-2])) / (float(ts[-1]) - float(ts[-2]))
        return float(ld[-1] + slope * (t - float(ts[-1])))
    i = int(np.searchsorted(ts, t, side="right"))
    t0, t1 = float(ts[i - 1]), float(ts[i])
    w = (t - t0) / (t1 - t0)
    return float((1.0 - w) * ld[i - 1] + w * ld[i])


def _bond_price_from_D_terminal(
    T_mat: float,
    y_par: float,
    terminal_log_discount: float,
    pillars_t: np.ndarray,
    pillars_logd: np.ndarray,
) -> float:
    """
    Price = 1 for par bond at T_mat with semiannual coupons y_par/2.
    Interior coupons use log-linear interp on existing pillars only; maturity uses
    terminal_log_discount (unknown when solving).
    """
    c = 0.5 * y_par
    times = _coupon_payment_times(T_mat)

    def logd_of(t: float) -> float:
        if t >= T_mat - 1e-15:
            return float(terminal_log_discount)
        return _log_discount_interp_segments(t, pillars_t, pillars_logd)

    pv = 0.0
    for t in times[:-1]:
        pv += c * math.exp(logd_of(t))
    t_last = times[-1]
    pv += (1.0 + c) * math.exp(logd_of(t_last))
    return pv


def bootstrap_curve(par_by_series: dict[str, float], record_date: str) -> TreasuryZeroCurve:
    """
    Build discount pillars at FRED_CM_TENORS_YEARS (short end proxy + bootstrapped long end).
    """
    series_order = [
        "DGS1MO",
        "DGS3MO",
        "DGS6MO",
        "DGS1",
        "DGS2",
        "DGS3",
        "DGS5",
        "DGS7",
        "DGS10",
        "DGS20",
        "DGS30",
    ]
    y_short = {s: par_by_series[s] for s in ("DGS1MO", "DGS3MO", "DGS6MO")}
    pillars_t: list[float] = []
    pillars_logd: list[float] = []

    for T, sid in zip(FRED_CM_TENORS_YEARS[:3], ("DGS1MO", "DGS3MO", "DGS6MO")):
        y = y_short[sid]
        d = math.exp(-y * T)
        pillars_t.append(T)
        pillars_logd.append(math.log(d))

    pt = np.asarray(pillars_t, dtype=float)
    pld = np.asarray(pillars_logd, dtype=float)

    for T_mat in COUPON_BOOTSTRAP_TENORS:
        sid = {
            1.0: "DGS1",
            2.0: "DGS2",
            3.0: "DGS3",
            5.0: "DGS5",
            7.0: "DGS7",
            10.0: "DGS10",
            20.0: "DGS20",
            30.0: "DGS30",
        }[T_mat]
        y_par = par_by_series[sid]

        def err(log_d_T: float) -> float:
            return _bond_price_from_D_terminal(T_mat, y_par, float(log_d_T), pt, pld) - 1.0

        lo, hi = -25.0, -1e-6
        fv_lo, fv_hi = err(lo), err(hi)
        if not math.isfinite(fv_lo) or not math.isfinite(fv_hi):
            raise RuntimeError(f"Bootstrap bracket non-finite at T={T_mat}")
        if fv_lo * fv_hi > 0:
            raise RuntimeError(f"Bootstrap bracket failed at T={T_mat} sid={sid}")

        log_d_T = brentq(err, lo, hi, xtol=1e-10, rtol=1e-10)
        d_T = math.exp(log_d_T)
        pillars_t.append(T_mat)
        pillars_logd.append(math.log(d_T))
        pt = np.asarray(pillars_t, dtype=float)
        pld = np.asarray(pillars_logd, dtype=float)

    return TreasuryZeroCurve(
        as_of_date=record_date,
        par_yields_decimal=dict(par_by_series),
        pillar_times=pillars_t,
        log_discounts=pillars_logd,
    )


def build_treasury_zero_curve(session: requests.Session | None = None) -> TreasuryZeroCurve:
    record_date, par = fetch_fred_cm_yields(session=session)
    return bootstrap_curve(par, record_date)


def try_build_treasury_zero_curve(
    session: requests.Session | None = None,
) -> tuple[TreasuryZeroCurve | None, str | None]:
    try:
        return build_treasury_zero_curve(session=session), None
    except Exception as e:
        return None, str(e)


def load_yield_curve_json(path: str | Path) -> tuple[TreasuryZeroCurve | None, str | None]:
    """Load curve written by fetch_data.py (yield_curve.json)."""
    p = Path(path)
    if not p.is_file():
        return None, f"not found: {p}"
    try:
        with p.open() as f:
            data = json.load(f)
        return TreasuryZeroCurve.from_saved_dict(data), None
    except Exception as e:
        return None, str(e)
