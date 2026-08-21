"""Shared preferred-stock Monte Carlo helpers (SATA + STRC).

Keeps issuer parameters in one place and maps them onto the existing
``sata_valuation.Configuration`` / simulation engine so we do not maintain
two copy-pasted dividend loops.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from strc_paths import OUTPUT_DIR, YIELD_CURVE_FALLBACK_PATH

# Last resort: used only if neither today's live curve nor the tracked
# fallback cache (yield_curve_fallback.json) is available — e.g. a fresh
# environment before any fetch has ever succeeded.
DEFAULT_DISCOUNT_RATE_ANNUAL = 0.04159

# Strive's holding of Strategy's STRC preferred, from the 10-Q for the quarter
# ended 2026-06-30 (filed 2026-08-10): 505,000 shares, $50.5M notional, carried
# at $42.9M fair value. The share count only moves on a filing, so it is pinned
# here and refreshed each quarter; the position is marked with the live quote.
STRC_SHARES_HELD = 505_000.0
STRC_SHARES_HELD_AS_OF = "2026-06-30"
STRC_SHARES_HELD_SOURCE = (
    "https://www.sec.gov/Archives/edgar/data/1920406/000162828026054985/"
    "asst-20260630.htm"
)

# Longest pillar FRED's constant-maturity Treasury series publishes (DGS30).
# The coupon stream being discounted is defaultable and heavily front-loaded
# in PV terms (not a true 100-year cash flow), so the longest live market
# rate available is a reasonable flat-rate proxy for the whole horizon.
DISCOUNT_RATE_TENOR_YEARS = 30.0


def live_yield_curve(output_dir: str | Path = OUTPUT_DIR) -> Any | None:
    """The best available TreasuryZeroCurve, or None if none is available.

    Tries, in order: (1) today's live-fetched output/yield_curve.json, (2) the
    tracked/committed yield_curve_fallback.json — last known good from any
    environment where a fetch previously succeeded, refreshed automatically
    on every successful fetch (see fetch_data.py). A stale committed curve is
    still real market data and meaningfully closer to current than a constant
    that's never updated.
    """
    from fetch_treasury_zero_yieldcurve import load_yield_curve_json

    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR
    for path in (output_dir / "yield_curve.json", YIELD_CURVE_FALLBACK_PATH):
        try:
            curve, _err = load_yield_curve_json(path)
        except Exception:
            continue
        if curve is not None:
            return curve
    return None


def _curve_to_annual_rate(curve: Any, tenor_years: float) -> float | None:
    """TreasuryZeroCurve's continuous rate at tenor_years -> the annual-
    compounding convention Configuration expects. None if not finite."""
    continuous_rate = curve.equivalent_constant_rate(tenor_years)
    if not math.isfinite(continuous_rate):
        return None
    return math.exp(continuous_rate) - 1


def _live_discount_rate_annual(output_dir: Path = OUTPUT_DIR) -> float:
    """30-year point on the best available Treasury curve, annually compounded.

    This is a SUMMARY figure for display/reporting only (e.g. the site's
    reference-rate label) — actual NPV discounting uses the full curve term
    structure month by month (see monthly_discount_factors_from_curve), not
    this single flattened number. Falls back to DEFAULT_DISCOUNT_RATE_ANNUAL
    if no curve is available at all.
    """
    curve = live_yield_curve(output_dir)
    if curve is not None:
        rate = _curve_to_annual_rate(curve, DISCOUNT_RATE_TENOR_YEARS)
        if rate is not None:
            return rate
    return DEFAULT_DISCOUNT_RATE_ANNUAL


def monthly_discount_factors_from_curve(curve: Any, total_months: int):
    """Per-month discount factors from the actual curve term structure.

    discount_factors[t] = 1 / curve.discount(T) for T = (t+1)/12 years, so
    calculate_npv_matrix_multiplication's cash_flows / discount_factors gives
    the correct PV at each month's own point on the curve — a 1-month cash
    flow is discounted at the ~1-month rate, not the same 30-year rate used
    for a cash flow 300 months out. Returns None if the curve can't produce a
    finite factor for every month (caller should fall back to a flat rate).
    """
    import numpy as np

    months = np.arange(1, total_months + 1, dtype=float)
    factors = np.empty(total_months, dtype=float)
    for i, t_years in enumerate(months / 12.0):
        d = curve.discount(t_years)
        if not math.isfinite(d) or d <= 0:
            return None
        factors[i] = 1.0 / d
    return factors


def _annual_zero_from_discount(T: float, discount: float) -> float | None:
    """Annually compounded zero implied by discount factor D(T)."""
    if T <= 0 or not math.isfinite(discount) or discount <= 0:
        return None
    return float(discount ** (-1.0 / T) - 1.0)


def build_yield_curve_chart_payload(
    output_dir: str | Path = OUTPUT_DIR,
    *,
    max_years: float = 40.0,
) -> dict[str, Any] | None:
    """Site-ready Treasury zero curve for the Preferreds discount chart.

    Samples the same interpolated/extrapolated zeros the valuation uses
    (monthly tenors through ``max_years``), plus the FRED bootstrap pillars.
    Returns None if no curve is available.
    """
    curve = live_yield_curve(output_dir)
    if curve is None:
        return None

    pillars: list[dict[str, Any]] = []
    for T, ld in zip(curve.pillar_times, curve.log_discounts):
        d = math.exp(ld)
        z = _annual_zero_from_discount(float(T), d)
        if z is None:
            continue
        pillars.append(
            {
                "years": float(T),
                "zero_annual": z,
                "discount": float(d),
            }
        )

    curve_pts: list[dict[str, Any]] = []
    n_months = int(round(max_years * 12))
    pillar_years = {round(float(T), 10) for T in curve.pillar_times}
    for m in range(1, n_months + 1):
        T = m / 12.0
        d = float(curve.discount(T))
        z = _annual_zero_from_discount(T, d)
        if z is None:
            continue
        # Mark points that land on a FRED pillar (monthly grid hits 1m/3m/6m/…).
        is_pillar = round(T, 10) in pillar_years
        curve_pts.append(
            {
                "years": T,
                "zero_annual": z,
                "is_pillar": is_pillar,
            }
        )

    ref_T = float(DISCOUNT_RATE_TENOR_YEARS)
    ref_d = float(curve.discount(ref_T))
    ref_z = _annual_zero_from_discount(ref_T, ref_d)

    return {
        "as_of_date": getattr(curve, "as_of_date", None),
        "source": getattr(curve, "source", None)
        or "FRED DGS* (fredgraph.csv) + semiannual par bootstrap",
        "flat_after_years": DISCOUNT_RATE_TENOR_YEARS,
        "reference_zero_annual": ref_z,
        "max_years": max_years,
        "pillars": pillars,
        "curve": curve_pts,
        "note": (
            "Annually compounded zeros from log-linear discount-factor "
            "interpolation between FRED pillars; flat zero beyond the "
            f"{DISCOUNT_RATE_TENOR_YEARS:.0f}y tenor."
        ),
    }


@dataclass
class PreferredIssuerConfig:
    """Issuer parameters for a Bitcoin-treasury preferred."""

    ticker: str
    shares_outstanding: int
    annual_dividend_rate: float  # e.g. 0.12 for 12%
    bitcoin_holdings: float
    cash_reserve: float
    par_value: float = 100.0
    market_price: float | None = None
    dividend_suspension_threshold_multiplier: float = 1.0
    discount_rate_annual: float = DEFAULT_DISCOUNT_RATE_ANNUAL
    # Preferred stock of another Bitcoin treasury company held on this issuer's
    # own balance sheet. Nets against the issuer's preferred claim when the
    # model decides whether Bitcoin may be sold. Strive holds STRC; Strategy
    # holds none, so this stays zero for STRC.
    held_preferred_shares: float = 0.0
    held_preferred_price: float | None = None

    def to_configuration_overrides(self) -> dict[str, Any]:
        """Map onto ``sata_valuation.Configuration`` override keys."""
        overrides: dict[str, Any] = {
            "sata_shares": self.shares_outstanding,
            "sata_dividend_rate": self.annual_dividend_rate,
            "bitcoin_holdings": self.bitcoin_holdings,
            "cash": self.cash_reserve,
            "discount_rate_annual": self.discount_rate_annual,
            "strc_shares_held": self.held_preferred_shares,
            "strc_market_price": self.held_preferred_price,
        }
        if self.market_price is not None:
            overrides["sata_current_price"] = self.market_price
        return overrides

    @property
    def held_preferred_value(self) -> float:
        """Mark-to-market of the held preferred position (0 without a quote)."""
        if not self.held_preferred_shares or not self.held_preferred_price:
            return 0.0
        return float(self.held_preferred_shares) * float(self.held_preferred_price)

    @property
    def net_claim_value(self) -> float:
        """Preferred claim at market, net of preferred held on the balance sheet."""
        price = self.market_price if self.market_price else self.par_value
        return max(self.shares_outstanding * float(price) - self.held_preferred_value, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cash_net_of_held_preferred(reported_cash: float, held_preferred_value: float) -> float:
    """Strip the held-preferred position out of a reported cash figure.

    strategytracker's ``cash`` for ASST lumps the STRC position in with cash and
    equivalents: at 2026-08-07 it reported $202.664M against the 10-Q's $154.9M
    cash + $48.0M STRC fair value (a 0.1% gap). Left alone, the model would
    spend STRC as if it were a bank balance and then net it against the claim
    as well — counting it twice. Cash means cash here; the STRC position earns
    its keep by reducing the claim Bitcoin has to cover, not by paying coupons.
    """
    if held_preferred_value <= 0:
        return reported_cash
    return max(reported_cash - held_preferred_value, 0.0)


def live_strc_price(output_dir: Path = OUTPUT_DIR) -> float | None:
    """Latest STRC quote: live Yahoo first, then whatever the fetches left behind.

    The position is only worth what it can be sold for today, and the cached
    JSON can be weeks stale (strc_data.json is written by option-chain fetches,
    not on a quote schedule). yahoo_spot_price goes through the 1-hour network
    cache, so this is one call per hour at worst and a no-op offline.
    """
    try:
        from fetch_yahoo import yahoo_spot_price

        price = yahoo_spot_price("STRC")
        if price:
            return float(price)
    except Exception:
        pass

    for name, key in (
        ("strc_data.json", "current_price"),
        ("mstr_treasury_extracted_data.json", "strc_price"),
        ("mstr_enriched_data.json", "strc_price"),
    ):
        path = output_dir / name
        if not path.is_file():
            continue
        try:
            with path.open() as f:
                price = json.load(f).get(key)
        except Exception:
            continue
        if price:
            return float(price)
    return None


def load_sata_issuer(output_dir: Path = OUTPUT_DIR) -> PreferredIssuerConfig:
    path = output_dir / "treasury_extracted_data.json"
    data: dict[str, Any] = {}
    if path.is_file():
        with path.open() as f:
            data = json.load(f)

    rate = float(data.get("sata_dividend_rate") or 0.13)
    if rate > 1:
        rate = rate / 100.0

    strc_shares = data.get("strc_shares_held")
    strc_price = data.get("strc_price") or live_strc_price(output_dir)
    held_shares = float(strc_shares) if strc_shares is not None else STRC_SHARES_HELD
    held_value = held_shares * float(strc_price) if strc_price else 0.0

    return PreferredIssuerConfig(
        ticker="SATA",
        shares_outstanding=int(data.get("sata_shares") or 7_513_910),
        annual_dividend_rate=rate,
        bitcoin_holdings=float(data.get("btc_holdings") or 19_032.3),
        cash_reserve=cash_net_of_held_preferred(
            float(data.get("cash") or 186_400_000.0), held_value
        ),
        market_price=float(data["sata_price"]) if data.get("sata_price") is not None else None,
        discount_rate_annual=_live_discount_rate_annual(output_dir),
        held_preferred_shares=held_shares,
        held_preferred_price=float(strc_price) if strc_price else None,
    )


def load_strc_issuer(output_dir: Path = OUTPUT_DIR) -> PreferredIssuerConfig:
    """Build STRC issuer config from MSTR treasury extracts."""
    hedge = {}
    enriched = {}
    hedge_path = output_dir / "mstr_treasury_extracted_data.json"
    enriched_path = output_dir / "mstr_enriched_data.json"
    if hedge_path.is_file():
        with hedge_path.open() as f:
            hedge = json.load(f)
    if enriched_path.is_file():
        with enriched_path.open() as f:
            enriched = json.load(f)

    shares = int(hedge.get("strc_shares") or enriched.get("strc_shares") or 0)
    rate = float(hedge.get("strc_dividend_rate") or enriched.get("strc_dividend_rate") or 0)
    if rate > 1:
        rate = rate / 100.0
    # Fall back to effective yield if dividend_rate is missing/out of range.
    eff = hedge.get("strc_effective_yield") or enriched.get("strc_effective_yield")
    if (rate <= 0 or rate > 0.5) and eff is not None:
        # strc_effective_yield is already a fractional rate (see
        # fetch_mstr_treasury.py's parse_strc_metrics_from_tracker normalization) —
        # only rescale it if it's ever supplied as a raw percentage number (>1).
        rate = float(eff)
        if rate > 1:
            rate = rate / 100.0

    btc = float(hedge.get("btc_holdings") or enriched.get("bitcoin_holdings") or 0)
    cash = float(hedge.get("usd_reserve_usd") or enriched.get("cash") or 0)
    price = hedge.get("strc_price") or enriched.get("strc_price")

    if shares <= 0:
        raise ValueError(
            "STRC shares missing — run fetch_mstr_treasury.py / fetch_data.py first"
        )

    return PreferredIssuerConfig(
        ticker="STRC",
        shares_outstanding=shares,
        annual_dividend_rate=rate if rate > 0 else 0.12,
        bitcoin_holdings=btc,
        cash_reserve=cash,
        market_price=float(price) if price is not None else None,
        discount_rate_annual=_live_discount_rate_annual(output_dir),
    )


def make_configuration(issuer: PreferredIssuerConfig, data_dir: Optional[str] = None):
    """Instantiate ``sata_valuation.Configuration`` for any preferred issuer."""
    from sata_valuation import Configuration

    cfg = Configuration(data_dir=data_dir, **issuer.to_configuration_overrides())
    cfg.sata_par_value = issuer.par_value
    cfg.dividend_suspension_threshold_multiplier = (
        issuer.dividend_suspension_threshold_multiplier
    )
    cfg.discount_rate_annual = issuer.discount_rate_annual
    return cfg
