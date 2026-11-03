"""Tests for strc_call_writer.py — discrete-dividend American call, ex-date calendar, cap math.

Builds its own inputs; no network or fetched data required.
"""

from __future__ import annotations

import math
from datetime import date

import pytest
from scipy.stats import norm

import strc_call_writer as w
from ibit_option_deltas import american_price_crr


def bs_call(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


# --- pricer ----------------------------------------------------------------


@pytest.mark.parametrize(
    "S,K,T,r,sigma",
    [(100.0, 100.0, 0.5, 0.04, 0.20), (99.78, 100.0, 0.1, 0.042, 0.05), (100.0, 105.0, 1.0, 0.045, 0.10)],
)
def test_no_dividend_american_call_is_european(S, K, T, r, sigma):
    """With no dividends and r > 0 early exercise is never optimal: matches Black-Scholes."""
    res = w.american_call_discrete_dividends(S, K, T, r, sigma)
    assert res.price == pytest.approx(bs_call(S, K, T, r, sigma), abs=2e-3)
    assert not len(res.boundary)


def test_daily_cash_dividends_match_continuous_yield_tree():
    """$12/yr paid daily in cash ≈ a continuous yield of 12/S on the CRR tree."""
    S, K, T, r, sigma = 99.78, 100.0, 0.37, 0.043, 0.08
    days = int(T * 365)
    times = [(i + 0.5) / 365 for i in range(days)]
    res = w.american_call_discrete_dividends(S, K, T, r, sigma, times, [12.0 / 365] * days)
    crr = american_price_crr(S, K, T, r, 12.0 / S, sigma, n_steps=1500, is_call=True)
    assert res.price == pytest.approx(crr, abs=0.02)


def test_large_dividend_creates_exercise_boundary_just_before_it():
    S, K, T, r, sigma, D = 110.0, 100.0, 0.5, 0.04, 0.20, 5.0
    res = w.american_call_discrete_dividends(S, K, T, r, sigma, [0.25], [D])
    escrowed_european = bs_call(S - D * math.exp(-r * 0.25), K, T, r, sigma)
    assert res.price >= S - K
    assert res.price > escrowed_european + 0.5  # the early-exercise premium is material
    assert K < res.boundary[0] < 120.0


def test_tiny_dividend_never_worth_exercising_for():
    """A dividend below the interest saved by paying the strike later never triggers exercise."""
    res = w.american_call_discrete_dividends(100.0, 100.0, 0.5, 0.05, 0.10, [0.25], [0.001])
    assert math.isinf(res.boundary[0])


def test_expiry_week_boundary_sits_just_above_strike_at_front_month_vol():
    """Friday expiry is itself an ex-date: at ~2.5% vol Thursday's exercise line is pennies above K."""
    cal = w.MarketCalendar(date(2027, 3, 1), date(2027, 3, 31))
    ladder = w.build_ex_dividend_ladder(date(2027, 3, 1), date(2027, 3, 31), cal, rate=0.12)
    b = w.expiry_week_boundary(date(2027, 3, 19), 100.0, 0.025, 0.043, cal, ladder)
    assert b is not None and 100.0 < b < 100.15


def test_implied_vol_round_trips():
    S, K, T, r = 99.78, 100.0, 0.3, 0.043
    times = [(i + 0.6) / 365 for i in range(int(T * 365))]
    divs = [12.0 / 365] * len(times)
    target = w.american_call_discrete_dividends(S, K, T, r, 0.07, times, divs).price
    assert w.implied_vol(target, S, K, T, r, times, divs) == pytest.approx(0.07, abs=2e-4)


def test_simulated_exercise_respects_boundary():
    times, divs = [0.1, 0.2], [0.05, 0.05]
    never = w.simulate_early_exercise(100.0, 100.0, 0.3, 0.04, 0.05, times, divs, [math.inf, math.inf], n_paths=2000)
    always = w.simulate_early_exercise(100.0, 100.0, 0.3, 0.04, 0.05, times, divs, [0.0, 0.0], n_paths=2000)
    assert never["p_early_exercise"] == 0.0
    assert always["p_early_exercise"] == 1.0
    assert always["exercise_index_counts"] == [2000, 0]


# --- calendar and dividend ladder -----------------------------------------

# Ex-dates Nasdaq lists for the 8-K's 1–30 Nov 2026 daily record dates.
NOV_2026_DECLARED_EX = {
    date(2026, 10, 30): [date(2026, 11, 1)],
    date(2026, 11, 2): [date(2026, 11, 2)],
    date(2026, 11, 6): [date(2026, 11, 6), date(2026, 11, 7), date(2026, 11, 8)],
    date(2026, 11, 10): [date(2026, 11, 10), date(2026, 11, 11)],  # Veterans Day: NYSE open, no settlement
    date(2026, 11, 12): [date(2026, 11, 12)],
    date(2026, 11, 20): [date(2026, 11, 20), date(2026, 11, 21), date(2026, 11, 22)],  # expiry Friday
    date(2026, 11, 25): [date(2026, 11, 25), date(2026, 11, 26)],  # Thanksgiving
    date(2026, 11, 27): [date(2026, 11, 27), date(2026, 11, 28), date(2026, 11, 29)],
    date(2026, 11, 30): [date(2026, 11, 30)],
}


def test_ex_dates_follow_t_plus_one_settlement():
    cal = w.MarketCalendar(date(2026, 10, 1), date(2026, 12, 31))
    for ex, records in NOV_2026_DECLARED_EX.items():
        for rec in records:
            assert cal.ex_date(rec) == ex, rec


def test_monthly_dividend_is_one_dollar_at_twelve_percent():
    for start, end in ((date(2026, 11, 1), date(2026, 11, 30)), (date(2027, 2, 1), date(2027, 2, 28))):
        total = sum(a for _, a in w.project_record_dividends(start, end, 0.12))
        assert total == pytest.approx(1.00, abs=1e-12)


def test_ladder_uses_declared_rows_then_projects_without_double_counting():
    cal = w.MarketCalendar(date(2026, 11, 1), date(2027, 1, 31))
    declared = [
        {"ex_date": date(2026, 11, 27), "record_date": date(2026, 11, 27), "amount": 0.10},
        {"ex_date": date(2026, 11, 30), "record_date": date(2026, 11, 30), "amount": 0.04},
    ]
    ladder = w.build_ex_dividend_ladder(date(2026, 11, 26), date(2027, 1, 31), cal, rate=0.12, declared=declared)
    assert ladder[0].ex_date == date(2026, 11, 27) and ladder[0].declared and ladder[0].amount == 0.10
    records = [d for e in ladder for d in e.record_dates]
    assert len(records) == len(set(records))
    projected = [e for e in ladder if not e.declared]
    first, last = projected[0].record_dates[0], projected[-1].record_dates[-1]
    assert first == date(2026, 12, 1)
    expected = sum(a for _, a in w.project_record_dividends(first, last, 0.12))
    assert sum(e.amount for e in projected) == pytest.approx(expected, abs=1e-12)


# --- cap / data helpers -----------------------------------------------------


def test_implied_cap_break_probability():
    assert w.implied_cap_break_probability(0.45, 0.07, 2.0) == pytest.approx(0.19)
    assert w.implied_cap_break_probability(0.05, 0.07, 1.0) == 0.0
    assert w.implied_cap_break_probability(3.0, 0.0, 1.0) is None
    assert w.annual_equivalent_probability(0.19, 0.5) == pytest.approx(1 - 0.81**2)


def test_parse_occ_symbol():
    assert w.parse_occ_symbol("STRC261120C00100000") == ("STRC", date(2026, 11, 20), "C", 100.0)
    assert w.parse_occ_symbol("STRC290119P00092500") == ("STRC", date(2029, 1, 19), "P", 92.5)


def test_naked_call_margin():
    # 20% of 99.78 less $0.22 OTM, plus premium.
    assert w.naked_call_margin(99.78, 100.0, 0.45) == pytest.approx(0.2 * 99.78 - 0.22 + 0.45)


def test_pinned_par_ranking_excludes_itm_strikes_and_charges_buyback_only_at_par():
    today = date(2026, 11, 3)
    mar, jun = date(2027, 3, 19), date(2027, 6, 17)
    contracts = [
        {"type": "C", "expiry": mar, "strike": 97.5, "bid": 2.00, "ask": 3.00},  # called at par
        {"type": "C", "expiry": mar, "strike": 100.0, "bid": 0.45, "ask": 0.55},
        {"type": "C", "expiry": mar, "strike": 105.0, "bid": 0.05, "ask": 0.20},
        {"type": "C", "expiry": jun, "strike": 100.0, "bid": 0.60, "ask": 1.20},
        {"type": "P", "expiry": mar, "strike": 100.0, "bid": 1.90, "ask": 6.60},
        {"type": "C", "expiry": jun, "strike": 105.0, "bid": None, "ask": 0.40},  # no bid
    ]
    rows = w.pinned_par_ranking(contracts, 99.78, today, rate=0.12)
    assert [(r["expiry"], r["strike"]) for r in rows] == [
        ("2027-03-19", 100.0), ("2027-06-17", 100.0), ("2027-03-19", 105.0)
    ]
    mar100 = rows[0]
    years = 136 / 365
    assert mar100["net_yr_bid"] == pytest.approx((0.45 - 0.05) / 99.78 / years)
    assert mar100["total_yr_bid"] == pytest.approx(12.0 / 99.78 + mar100["net_yr_bid"])
    assert rows[2]["net_yr_bid"] == pytest.approx(rows[2]["premium_yr_bid"])  # no buyback above par
