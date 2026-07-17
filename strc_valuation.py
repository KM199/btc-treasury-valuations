#!/usr/bin/env python3
"""STRC preferred Monte Carlo valuation (shared engine with SATA).

Uses ``preferred_valuation`` + ``sata_valuation`` simulation workers so STRC
and SATA do not maintain duplicate dividend loops.

  python strc_valuation.py [--baseline-only] [--data-dir output]
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from multiprocessing import cpu_count
from pathlib import Path

import numpy as np

from preferred_valuation import load_strc_issuer, make_configuration
from sata_valuation import (
    BaselineResults,
    generate_baseline_plots,
    generate_npv_plots,
    load_price_paths,
    run_baseline_analysis,
    save_results_to_json,
    setup_logging,
    validate_arguments,
)
from strc_paths import OUTPUT_DIR, PLOTS_DIR, ensure_output_dirs


def main() -> None:
    parser = argparse.ArgumentParser(description="STRC preferred valuation (shared MC engine)")
    parser.add_argument("--data-dir", type=str, default=str(OUTPUT_DIR))
    parser.add_argument(
        "--output",
        type=str,
        default=str(OUTPUT_DIR / "strc_valuation_results.json"),
    )
    parser.add_argument("--plots-dir", type=str, default=str(PLOTS_DIR))
    parser.add_argument("--num-workers", type=int, default=None)
    parser.add_argument("--optimization-level", type=int, choices=[0, 1, 2], default=2)
    parser.add_argument("--baseline-only", action="store_true", default=True)
    parser.add_argument("--full", action="store_true", help="Reserved; currently baseline-only")
    args = parser.parse_args()

    validate_arguments(args)
    logger = setup_logging()
    ensure_output_dirs()
    os.makedirs(args.plots_dir, exist_ok=True)

    data_dir = Path(args.data_dir)
    issuer = load_strc_issuer(data_dir)
    config = make_configuration(issuer, data_dir=str(data_dir))
    config.optimization_level = args.optimization_level
    config.enable_early_termination = args.optimization_level >= 1
    config.validate()

    logger.info(
        "STRC issuer: shares=%s rate=%.2f%% BTC=%.1f cash=$%.0f market=%s",
        f"{issuer.shares_outstanding:,}",
        issuer.annual_dividend_rate * 100,
        issuer.bitcoin_holdings,
        issuer.cash_reserve,
        issuer.market_price,
    )

    price_data = load_price_paths(str(data_dir))
    scenarios = price_data["scenarios"]
    baseline_idx = min(range(len(scenarios)), key=lambda i: abs(scenarios[i]["starting_price_pct"]))
    baseline_price_paths = np.array(scenarios[baseline_idx]["price_paths"])

    config_dict = config.to_dict()
    config_dict.update(
        {
            "num_simulations": price_data["num_simulations"],
            "simulation_years": price_data["simulation_years"],
            "total_months": price_data["total_months"],
            "current_bitcoin_price": price_data["current_bitcoin_price"],
        }
    )

    total_months = config_dict["total_months"]
    monthly_discount_rate = config_dict["monthly_discount_rate"]
    config_dict["discount_factors"] = np.power(
        1 + monthly_discount_rate, np.arange(1, total_months + 1)
    )

    num_workers = args.num_workers or config.default_num_workers or cpu_count()
    print(f"Using {num_workers} worker processes")

    t0 = time.time()
    months_paid, _btc, _cash, unpaid, npvs = run_baseline_analysis(
        baseline_price_paths, config_dict, num_workers
    )
    npvs_per_share = npvs / config.sata_shares_outstanding
    elapsed = time.time() - t0

    fair = float(npvs_per_share.mean())
    baseline = BaselineResults(
        final_valuation_per_share=fair,
        final_valuation_total=float(npvs.mean()),
        valuation_vs_par=(fair / config.sata_par_value - 1) * 100,
        mean_months_paid=float(months_paid.mean()),
        median_months_paid=float(np.median(months_paid)),
        mean_accumulated_unpaid=float(unpaid.mean()),
        mean_npv_per_share=fair,
        median_npv_per_share=float(np.median(npvs_per_share)),
        std_npv_per_share=float(npvs_per_share.std()),
        cv_npv_per_share=float(npvs_per_share.std() / fair) if fair else 0.0,
    )

    _, img1 = generate_baseline_plots(months_paid, _btc, unpaid, args.plots_dir)
    _, img2 = generate_npv_plots(npvs_per_share, months_paid, args.plots_dir)

    from preferred_story import build_density_histogram

    results = {
        "metadata": {
            "ticker": "STRC",
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": elapsed,
            "issuer": issuer.to_dict(),
            "engine": "preferred_valuation + sata_valuation",
            "mode": "baseline_only",
        },
        "configuration": {
            "shares": config.sata_shares_outstanding,
            "annual_dividend_rate": config.sata_annual_dividend_rate,
            "par_value": config.sata_par_value,
            "bitcoin_holdings": config.initial_bitcoin_holdings,
            "cash_reserve": config.initial_cash_reserve,
            "discount_rate_annual": config.discount_rate_annual,
            "threshold_multiplier": config.dividend_suspension_threshold_multiplier,
        },
        "baseline_results": {
            "final_valuation_per_share": baseline.final_valuation_per_share,
            "final_valuation_total": baseline.final_valuation_total,
            "mean_npv_per_share": baseline.mean_npv_per_share,
            "median_npv_per_share": baseline.median_npv_per_share,
            "std_npv_per_share": baseline.std_npv_per_share,
            "mean_months_paid": baseline.mean_months_paid,
            "median_months_paid": baseline.median_months_paid,
            "mean_accumulated_unpaid": baseline.mean_accumulated_unpaid,
            "valuation_vs_par": baseline.valuation_vs_par,
            "market_price": issuer.market_price,
        },
        "baseline_histograms": {
            "months_paid": build_density_histogram(months_paid, n_bins=48),
            "npv_per_share": build_density_histogram(npvs_per_share, n_bins=48),
        },
        "scenario_results": [],
        "sensitivity_results": [],
        "plot_images": {
            "baseline_dividend_sustainability": img1,
            "baseline_npv_distribution": img2,
        },
    }

    save_results_to_json(results, args.output)
    print(f"\n✓ STRC fair value/share: ${fair:,.2f}")
    if issuer.market_price:
        gap = fair - issuer.market_price
        print(f"  Market ${issuer.market_price:,.2f}  →  gap ${gap:+,.2f}")
    print(f"  Wrote {args.output}")


if __name__ == "__main__":
    main()
