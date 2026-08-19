"""Deterministic preferred-story helpers for site export (no Monte Carlo).

Ports months-to-price math from sata_playground.ipynb and shapes
sata_valuation_results.json into a chart-ready preferred_story payload.
"""

from __future__ import annotations

from typing import Any


def monthly_discount_rate(annual_rate: float) -> float:
    return (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0


def npv_certain_dividends(
    monthly_payment: float, annual_discount_rate: float, num_months: int
) -> float:
    if num_months <= 0 or monthly_payment <= 0:
        return 0.0
    r = monthly_discount_rate(annual_discount_rate)
    if abs(r) < 1e-15:
        return monthly_payment * num_months
    return sum(monthly_payment / ((1.0 + r) ** n) for n in range(1, num_months + 1))


def find_months_to_price(
    monthly_payment: float,
    annual_discount_rate: float,
    target_price: float,
    *,
    max_months: int = 10000,
) -> int | None:
    """Months of certain dividends whose NPV equals target_price."""
    if monthly_payment <= 0 or target_price <= 0:
        return None
    low, high = 1, max_months
    if npv_certain_dividends(monthly_payment, annual_discount_rate, high) < target_price:
        return None
    while low < high:
        mid = (low + high) // 2
        npv = npv_certain_dividends(monthly_payment, annual_discount_rate, mid)
        if npv < target_price:
            low = mid + 1
        else:
            high = mid
    return low


def cumulative_pv_series(
    monthly_payment: float,
    annual_discount_rate: float,
    *,
    max_months: int = 240,
    step: int = 1,
) -> list[dict[str, float]]:
    r = monthly_discount_rate(annual_discount_rate)
    pts: list[dict[str, float]] = []
    cum = 0.0
    for n in range(1, max_months + 1):
        if abs(r) < 1e-15:
            cum = monthly_payment * n
        else:
            cum += monthly_payment / ((1.0 + r) ** n)
        if n % step == 0 or n == max_months:
            pts.append({"month": float(n), "pv": cum})
    return pts


def _breakeven_block(
    *,
    monthly_payment: float,
    annual_discount_rate: float,
    par: float,
    market_price: float | None,
) -> dict[str, Any]:
    months_par = find_months_to_price(
        monthly_payment, annual_discount_rate, par
    )
    months_mkt = None
    if market_price is not None and market_price > 0:
        months_mkt = find_months_to_price(
            monthly_payment, annual_discount_rate, float(market_price)
        )
    horizon = max(
        240,
        int((months_par or 120) * 1.4),
        int((months_mkt or 120) * 1.4),
    )
    return {
        "monthly_dividend": monthly_payment,
        "annual_discount_rate": annual_discount_rate,
        "par": par,
        "market_price": market_price,
        "months_to_par": months_par,
        "months_to_market": months_mkt,
        "pv_curve": cumulative_pv_series(
            monthly_payment, annual_discount_rate, max_months=horizon, step=1
        ),
    }


def _config_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "num_simulations",
        "simulation_years",
        "total_months",
        "current_bitcoin_price",
        "sata_shares_outstanding",
        "sata_annual_dividend_rate",
        "sata_par_value",
        "sata_monthly_dividend_per_share",
        "sata_monthly_dividend_total",
        "initial_bitcoin_holdings",
        "initial_cash_reserve",
        "dividend_suspension_threshold_multiplier",
        "discount_rate_annual",
        "monthly_discount_rate",
        "compounded_dividend_start_rate",
        "compounded_dividend_increment",
        "compounded_dividend_max_rate",
        # Netting of preferred held on the issuer's own balance sheet — the
        # base the Bitcoin-sale gate is measured against.
        "sata_market_price",
        "sata_market_claim",
        "strc_shares_held",
        "strc_market_price",
        "strc_position_value",
        "coverage_claim_value",
    )
    out = {k: cfg.get(k) for k in keys if k in cfg}
    # STRC configs (strc_valuation.py) use plain, unprefixed key names instead of
    # SATA's sata_-prefixed ones — alias them onto the same normalized fields.
    if "strc_shares_outstanding" in cfg:
        out["shares_outstanding"] = cfg["strc_shares_outstanding"]
    elif "sata_shares_outstanding" in cfg:
        out["shares_outstanding"] = cfg["sata_shares_outstanding"]
    elif "shares" in cfg:
        out["shares_outstanding"] = cfg["shares"]
    if "strc_annual_dividend_rate" in cfg:
        out["annual_dividend_rate"] = cfg["strc_annual_dividend_rate"]
    elif "sata_annual_dividend_rate" in cfg:
        out["annual_dividend_rate"] = cfg["sata_annual_dividend_rate"]
    elif "annual_dividend_rate" in cfg:
        out["annual_dividend_rate"] = cfg["annual_dividend_rate"]
    if "strc_monthly_dividend_per_share" in cfg:
        out["monthly_dividend_per_share"] = cfg["strc_monthly_dividend_per_share"]
    elif "sata_monthly_dividend_per_share" in cfg:
        out["monthly_dividend_per_share"] = cfg["sata_monthly_dividend_per_share"]
    if "sata_par_value" in cfg:
        out["par_value"] = cfg["sata_par_value"]
    elif "par_value" in cfg:
        out["par_value"] = cfg["par_value"]
    if "initial_bitcoin_holdings" in cfg:
        out["initial_bitcoin_holdings"] = cfg["initial_bitcoin_holdings"]
    elif "bitcoin_holdings" in cfg:
        out["initial_bitcoin_holdings"] = cfg["bitcoin_holdings"]
    if "initial_cash_reserve" in cfg:
        out["initial_cash_reserve"] = cfg["initial_cash_reserve"]
    elif "cash_reserve" in cfg:
        out["initial_cash_reserve"] = cfg["cash_reserve"]
    if "dividend_suspension_threshold_multiplier" in cfg:
        out["dividend_suspension_threshold_multiplier"] = cfg["dividend_suspension_threshold_multiplier"]
    elif "threshold_multiplier" in cfg:
        out["dividend_suspension_threshold_multiplier"] = cfg["threshold_multiplier"]
    return out


def _baseline_block(base: dict[str, Any]) -> dict[str, Any]:
    return {
        "fair_value": base.get("final_valuation_per_share")
        or base.get("mean_npv_per_share"),
        "fair_total": base.get("final_valuation_total"),
        "valuation_vs_par": base.get("valuation_vs_par"),
        "mean_months_paid": base.get("mean_months_paid"),
        "median_months_paid": base.get("median_months_paid"),
        "mean_accumulated_unpaid": base.get("mean_accumulated_unpaid"),
        "mean_npv": base.get("mean_npv_per_share"),
        "median_npv": base.get("median_npv_per_share"),
        "std_npv": base.get("std_npv_per_share"),
        "cv_npv": base.get("cv_npv_per_share"),
    }


def build_density_histogram(
    values: Any,
    *,
    n_bins: int = 40,
    note: str = "Empirical histogram from baseline Monte Carlo paths.",
) -> dict[str, Any] | None:
    """Probability-mass histogram for site charts (density sums to 1)."""
    try:
        import numpy as np
    except ImportError:
        return None
    arr = np.asarray(values, dtype=np.float64).ravel()
    if arr.size == 0:
        return None
    lo = float(arr.min())
    hi = float(arr.max())
    if not np.isfinite(lo) or not np.isfinite(hi):
        return None
    # Integer-like series (months paid): bin on integers when the range is small.
    int_like = np.all(np.isclose(arr, np.round(arr)))
    if int_like and hi - lo <= 80:
        edges = np.arange(np.floor(lo), np.ceil(hi) + 2) - 0.5
        counts, edges = np.histogram(arr, bins=edges)
    elif hi <= lo:
        edges = np.array([lo - 0.5, lo + 0.5], dtype=np.float64)
        counts = np.array([arr.size], dtype=np.float64)
    else:
        counts, edges = np.histogram(arr, bins=min(n_bins, max(8, arr.size // 20)))
    total = float(counts.sum())
    density = (counts / total).tolist() if total > 0 else [0.0] * len(counts)
    return {
        "approximate": False,
        "note": note,
        "bin_edges": edges.astype(float).tolist(),
        "density": density,
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "std": float(arr.std()),
        "min": lo,
        "max": hi,
        "n": int(arr.size),
    }


def _histogram_from_results(
    results: dict[str, Any], key: str
) -> dict[str, Any] | None:
    """Return an empirical histogram, or None. Never invents shapes from moments."""
    block = results.get("baseline_histograms") or {}
    hist = block.get(key) if isinstance(block, dict) else None
    if not isinstance(hist, dict):
        return None
    if hist.get("approximate"):
        return None
    if not hist.get("bin_edges") or not hist.get("density"):
        return None
    out = dict(hist)
    out["approximate"] = False
    return out


def _scenario_enriched(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = results.get("scenario_results") or []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fair = row.get("mean_npv_per_share") or row.get("final_valuation_per_share")
        parsed.append(
            {
                "btc_start_pct": row.get("starting_price_pct"),
                "btc_start": row.get("starting_price"),
                "fair_value": fair,
                "median_npv": row.get("median_npv_per_share"),
                "mean_months_paid": row.get("mean_months_paid"),
                "std_npv": row.get("std_npv_per_share"),
            }
        )
    if not parsed:
        return []
    baseline = min(
        parsed,
        key=lambda r: abs(float(r.get("btc_start_pct") or 0.0)),
    )
    base_fair = float(baseline.get("fair_value") or 0.0)
    out = []
    for r in parsed:
        fair = r.get("fair_value")
        pct = float(r.get("btc_start_pct") or 0.0)
        fair_f = float(fair) if fair is not None else None
        change_pct = None
        elasticity = None
        if fair_f is not None and base_fair:
            change_pct = ((fair_f - base_fair) / base_fair) * 100.0
            if abs(pct) > 1e-9:
                elasticity = change_pct / (pct * 100.0)
        out.append(
            {
                **r,
                "npv_change_vs_baseline_pct": change_pct,
                "elasticity": elasticity,
            }
        )
    return out


def _sensitivity_series(
    rows: list[Any],
    *,
    x_key: str,
    x_out: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                x_out: row.get(x_key),
                "fair_value": row.get("mean_npv_per_share")
                or row.get("final_valuation_per_share"),
                "mean_months_paid": row.get("mean_months_paid"),
                "median_npv": row.get("median_npv_per_share"),
                "std_npv": row.get("std_npv_per_share"),
                "btc_holdings": row.get("btc_holdings"),
                "dividend_rate_change_pct": row.get("dividend_rate_change_pct"),
            }
        )
    return out


def build_issuer_story(
    results: dict[str, Any],
    *,
    ticker: str,
    market_price: float | None,
) -> dict[str, Any]:
    cfg = results.get("configuration") or {}
    base = results.get("baseline_results") or {}

    monthly = (
        cfg.get("sata_monthly_dividend_per_share")
        or cfg.get("strc_monthly_dividend_per_share")
        or cfg.get("monthly_dividend_per_share")
    )
    annual_div = (
        cfg.get("sata_annual_dividend_rate")
        or cfg.get("strc_annual_dividend_rate")
        or cfg.get("annual_dividend_rate")
    )
    par = float(cfg.get("sata_par_value") or cfg.get("par_value") or 100.0)
    discount = float(cfg.get("discount_rate_annual") or 0.04)
    if monthly is None and annual_div is not None:
        monthly = float(annual_div) * par / 12.0
    monthly_f = float(monthly or 0.0)

    baseline = _baseline_block(base)
    # Never invent shapes from moments — only empirical Monte Carlo histograms.
    npv_hist = _histogram_from_results(results, "npv_per_share")
    months_hist = _histogram_from_results(results, "months_paid")

    meta = results.get("metadata") or {}
    return {
        "ticker": ticker,
        "status": "ready",
        "valuation_as_of": meta.get("timestamp") or meta.get("generated_at"),
        "configuration": _config_snapshot(cfg),
        "breakeven": _breakeven_block(
            monthly_payment=monthly_f,
            annual_discount_rate=discount,
            par=par,
            market_price=market_price,
        ),
        "baseline": baseline,
        "npv_histogram": npv_hist,
        "months_paid_histogram": months_hist,
        "scenarios": _scenario_enriched(results),
        "threshold_sensitivity": _sensitivity_series(
            results.get("sensitivity_results") or [],
            x_key="threshold_multiplier",
            x_out="threshold_multiplier",
        ),
        "dividend_rate_sensitivity": _sensitivity_series(
            results.get("dividend_rate_sensitivity_results") or [],
            x_key="dividend_rate",
            x_out="dividend_rate",
        ),
    }


def build_btc_path_fan(
    *,
    paths_npy: Any = None,
    metadata: dict[str, Any] | None = None,
    months: int = 120,
    n_sample_paths: int = 36,
    stride: int = 1,
) -> dict[str, Any] | None:
    """Compact baseline-scenario path fan for the website (not the full .npy).

    Expects price_paths shaped (n_scenarios, n_sims, n_months). Uses the middle
    scenario (0% BTC start shock).
    """
    try:
        import numpy as np
    except ImportError:
        return None

    if paths_npy is None:
        return None
    arr = np.asarray(paths_npy)
    if arr.ndim != 3 or arr.shape[0] < 1:
        return None

    mid = arr.shape[0] // 2
    block = arr[mid]  # (n_sims, n_months)
    n_sims, n_months = block.shape
    months = int(min(months, n_months))
    block = block[:, :months]

    pcts = (5, 25, 50, 75, 95)
    percentile_rows = {
        f"p{p}": np.percentile(block, p, axis=0).astype(float).tolist()
        for p in pcts
    }
    mean_arr = block.mean(axis=0)
    std_arr = block.std(axis=0)
    mean_path = mean_arr.astype(float).tolist()
    std_path = std_arr.astype(float).tolist()

    rng = np.random.default_rng(42)
    n_take = min(n_sample_paths, n_sims)
    idxs = rng.choice(n_sims, size=n_take, replace=False)
    samples = []
    for i, sim_i in enumerate(idxs):
        series = block[int(sim_i), ::stride].astype(float).tolist()
        samples.append({"id": int(i), "prices": series})

    start = float(block[0, 0])
    meta = metadata or {}
    return {
        "scenario_index": int(mid),
        "starting_price": start,
        "months": int(months),
        "stride": int(stride),
        "n_simulations": int(n_sims),
        "n_sample_paths": int(n_take),
        "month_index": list(range(0, months, stride)),
        "mean": mean_path[::stride],
        "std": std_path[::stride],
        # Site chart uses percentiles only. mean±kσ in dollar space is
        # misleading for right-skewed BTC prices (mean−2σ hits a floor).
        "percentiles": {k: v[::stride] for k, v in percentile_rows.items()},
        "samples": samples,
        "distribution": {
            "mean": _scalar(meta.get("distribution_mean")),
            "std": _scalar(meta.get("distribution_std")),
            "skew": _scalar(meta.get("distribution_skew")),
            "kurtosis": _scalar(meta.get("distribution_kurtosis")),
        },
        "note": (
            "Baseline (0% start) path fan — sample paths, mean, median, and "
            "cross-sectional percentiles (p5/p25/p75/p95). Full Monte Carlo "
            "stays in output/*.npy."
        ),
    }


def _scalar(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def historical_monthly_return_stats(output_dir: Any) -> dict[str, Any] | None:
    """Mean / vol / skew / excess kurtosis of historical monthly BTC log returns.

    Uses ``btc_historical_data.json`` (same series ``btc_price_paths.py`` compares
    against the manual distribution). Pandas skew/kurtosis match that printout.
    """
    try:
        import json
        from pathlib import Path

        import pandas as pd
    except ImportError:
        return None

    path = Path(output_dir) / "btc_historical_data.json"
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
        returns = data.get("monthly_returns", {}).get("returns")
        if not returns:
            return None
        series = pd.Series(returns, dtype=float)
        date_range = data.get("date_range") or {}
        return {
            "mean": float(series.mean()),
            "std": float(series.std()),
            "skew": float(series.skew()),
            "kurtosis": float(series.kurtosis()),
            "n_months": int(len(series)),
            "start": date_range.get("start"),
            "end": date_range.get("end"),
        }
    except (OSError, TypeError, ValueError, KeyError):
        return None


def load_btc_path_fan_from_output(output_dir: Any) -> dict[str, Any] | None:
    """Memmap the scenarios npy and build a website-sized fan summary."""
    try:
        import numpy as np
        from pathlib import Path
    except ImportError:
        return None

    root = Path(output_dir)
    npy = root / "btc_price_paths_scenarios_price_paths.npy"
    meta_path = root / "btc_price_paths_scenarios_metadata.npz"
    if not npy.is_file():
        return None
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        with np.load(meta_path) as z:
            meta = {k: z[k] for k in z.files}
    arr = np.load(npy, mmap_mode="r")
    fan = build_btc_path_fan(paths_npy=arr, metadata=meta, months=240, n_sample_paths=36)
    if fan is not None:
        hist = historical_monthly_return_stats(root)
        if hist is not None:
            fan["historical_distribution"] = hist
    return fan


def build_preferred_story(
    *,
    sata_results: dict[str, Any] | None,
    strc_results: dict[str, Any] | None,
    sata_market: float | None,
    strc_market: float | None,
) -> dict[str, Any]:
    issuers: dict[str, Any] = {}
    if sata_results:
        issuers["SATA"] = build_issuer_story(
            sata_results, ticker="SATA", market_price=sata_market
        )
    else:
        issuers["SATA"] = {"ticker": "SATA", "status": "missing"}

    if strc_results:
        issuers["STRC"] = build_issuer_story(
            strc_results, ticker="STRC", market_price=strc_market
        )
    else:
        issuers["STRC"] = {
            "ticker": "STRC",
            "status": "model_pending",
            "breakeven": None,
            "baseline": None,
            "scenarios": [],
            "threshold_sensitivity": [],
            "dividend_rate_sensitivity": [],
        }
        # Still compute deterministic breakeven for STRC if we know coupon ~ variable;
        # Stretch is typically ~9–10% class — skip without config.

    return {
        "as_of": None,  # filled by caller
        "issuers": issuers,
        "order": ["STRC", "SATA"],
    }
