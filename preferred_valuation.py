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

from strc_paths import OUTPUT_DIR

# Fallback when yield_curve.json is missing/unreadable (e.g. before the first
# fetch_data.py run). Not otherwise used once a live curve is available.
DEFAULT_DISCOUNT_RATE_ANNUAL = 0.04159

# Longest pillar FRED's constant-maturity Treasury series publishes (DGS30).
# The coupon stream being discounted is defaultable and heavily front-loaded
# in PV terms (not a true 100-year cash flow), so the longest live market
# rate available is a reasonable flat-rate proxy for the whole horizon.
DISCOUNT_RATE_TENOR_YEARS = 30.0


def _live_discount_rate_annual(output_dir: Path = OUTPUT_DIR) -> float:
    """Long-run discount rate from the live Treasury zero curve (annually compounded).

    Falls back to DEFAULT_DISCOUNT_RATE_ANNUAL if yield_curve.json is missing,
    unreadable, or doesn't yield a finite rate.
    """
    from fetch_treasury_zero_yieldcurve import load_yield_curve_json

    try:
        curve, _err = load_yield_curve_json(output_dir / "yield_curve.json")
        if curve is None:
            return DEFAULT_DISCOUNT_RATE_ANNUAL
        continuous_rate = curve.equivalent_constant_rate(DISCOUNT_RATE_TENOR_YEARS)
        if not math.isfinite(continuous_rate):
            return DEFAULT_DISCOUNT_RATE_ANNUAL
        return math.exp(continuous_rate) - 1
    except Exception:
        return DEFAULT_DISCOUNT_RATE_ANNUAL


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

    def to_configuration_overrides(self) -> dict[str, Any]:
        """Map onto ``sata_valuation.Configuration`` override keys."""
        overrides: dict[str, Any] = {
            "sata_shares": self.shares_outstanding,
            "sata_dividend_rate": self.annual_dividend_rate,
            "bitcoin_holdings": self.bitcoin_holdings,
            "cash": self.cash_reserve,
        }
        if self.market_price is not None:
            overrides["sata_current_price"] = self.market_price
        return overrides

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_sata_issuer(output_dir: Path = OUTPUT_DIR) -> PreferredIssuerConfig:
    path = output_dir / "treasury_extracted_data.json"
    data: dict[str, Any] = {}
    if path.is_file():
        with path.open() as f:
            data = json.load(f)

    rate = float(data.get("sata_dividend_rate") or 0.13)
    if rate > 1:
        rate = rate / 100.0

    return PreferredIssuerConfig(
        ticker="SATA",
        shares_outstanding=int(data.get("sata_shares") or 7_513_910),
        annual_dividend_rate=rate,
        bitcoin_holdings=float(data.get("btc_holdings") or 19_032.3),
        cash_reserve=float(data.get("cash") or 186_400_000.0),
        market_price=float(data["sata_price"]) if data.get("sata_price") is not None else None,
        discount_rate_annual=_live_discount_rate_annual(output_dir),
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
