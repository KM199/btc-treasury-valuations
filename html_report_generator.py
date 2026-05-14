#!/usr/bin/env python3
"""
HTML Report Generator for SATA Preferred Equity Valuation Results

This script generates formatted HTML reports from JSON results produced by sata_valuation.py.
"""

import json
import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import pandas as pd
import numpy as np

from strc_paths import OUTPUT_DIR as DEFAULT_OUTPUT_DIR, REPORTS_DIR, ensure_output_dirs

# ============================================================================
# HTML REPORT GENERATION
# ============================================================================

def generate_html_report(config_dict: Dict[str, Any], baseline_results, scenario_results, sensitivity_results,
                         dividend_rate_sensitivity_results, btc_credit_sensitivity_results, plot_images, output_file):
    """Generate formatted HTML report with embedded images and tables."""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SATA Preferred Equity Valuation Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
        }}
        .header p {{
            margin: 10px 0 0 0;
            opacity: 0.9;
        }}
        .section {{
            background: white;
            padding: 30px;
            margin-bottom: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            color: #667eea;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
            margin-top: 0;
        }}
        .section h3 {{
            color: #764ba2;
            margin-top: 25px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        table th, table td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        table th {{
            background-color: #667eea;
            color: white;
            font-weight: bold;
        }}
        table tr:hover {{
            background-color: #f5f5f5;
        }}
        .metric {{
            display: inline-block;
            margin: 15px 20px 15px 0;
            padding: 15px 20px;
            background: #f8f9fa;
            border-left: 4px solid #667eea;
            border-radius: 5px;
        }}
        .metric-label {{
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }}
        .metric-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #333;
        }}
        img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin: 20px 0;
        }}
        .plot-container {{
            text-align: center;
            margin: 30px 0;
        }}
        .summary-box {{
            background: #e8f4f8;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>SATA Preferred Equity Valuation Report</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
"""

    # Configuration Section
    html_content += f"""
    <div class="section">
        <h2>Configuration</h2>
        <div class="summary-box">
            <h3>Simulation Parameters</h3>
            <div class="metric">
                <div class="metric-label">Number of Simulations</div>
                <div class="metric-value">{config_dict['num_simulations']:,}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Projection Period</div>
                <div class="metric-value">{config_dict['simulation_years']} years</div>
            </div>
        </div>
        <div class="summary-box">
            <h3>SATA Preferred Stock</h3>
            <div class="metric">
                <div class="metric-label">Shares Outstanding</div>
                <div class="metric-value">{config_dict['sata_shares_outstanding']:,}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Dividend Rate</div>
                <div class="metric-value">{config_dict['sata_annual_dividend_rate']:.2%}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Monthly Dividend per Share</div>
                <div class="metric-value">${config_dict['sata_monthly_dividend_per_share']:.3f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Monthly Dividend</div>
                <div class="metric-value">${config_dict['sata_monthly_dividend_total']:,.2f}</div>
            </div>
        </div>
        <div class="summary-box">
            <h3>Initial Conditions</h3>
            <div class="metric">
                <div class="metric-label">Bitcoin Holdings</div>
                <div class="metric-value">{config_dict['initial_bitcoin_holdings']:,.2f} BTC</div>
            </div>
            <div class="metric">
                <div class="metric-label">Cash Reserve</div>
                <div class="metric-value">${config_dict['initial_cash_reserve']:,.0f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Current Bitcoin Price</div>
                <div class="metric-value">${config_dict['current_bitcoin_price']:,.2f}</div>
            </div>
        </div>
        <div class="summary-box">
            <h3>Financial Parameters</h3>
            <div class="metric">
                <div class="metric-label">Discount Rate (Annual)</div>
                <div class="metric-value">{config_dict['discount_rate_annual']:.2%}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Suspension Threshold</div>
                <div class="metric-value">{config_dict['dividend_suspension_threshold_multiplier']:.2f}x par value</div>
            </div>
        </div>
    </div>
"""

    # Baseline Results Section
    if baseline_results:
        html_content += f"""
    <div class="section">
        <h2>Baseline Scenario Results</h2>
        <div class="summary-box">
            <h3>Valuation Summary</h3>
            <div class="metric">
                <div class="metric-label">Estimated Fair Value per Share</div>
                <div class="metric-value">${baseline_results.final_valuation_per_share:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Total Fair Value</div>
                <div class="metric-value">${baseline_results.final_valuation_total:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Valuation vs Par</div>
                <div class="metric-value">{baseline_results.valuation_vs_par:+.2f}%</div>
            </div>
        </div>
        <div class="summary-box">
            <h3>Dividend Sustainability</h3>
            <div class="metric">
                <div class="metric-label">Average Months Paid</div>
                <div class="metric-value">{baseline_results.mean_months_paid:.1f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Median Months Paid</div>
                <div class="metric-value">{baseline_results.median_months_paid:.1f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Mean Accumulated Unpaid</div>
                <div class="metric-value">${baseline_results.mean_accumulated_unpaid:,.2f}</div>
            </div>
        </div>
        <div class="summary-box">
            <h3>NPV Statistics</h3>
            <div class="metric">
                <div class="metric-label">Mean NPV per Share</div>
                <div class="metric-value">${baseline_results.mean_npv_per_share:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Median NPV per Share</div>
                <div class="metric-value">${baseline_results.median_npv_per_share:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Standard Deviation</div>
                <div class="metric-value">${baseline_results.std_npv_per_share:,.2f}</div>
            </div>
            <div class="metric">
                <div class="metric-label">Coefficient of Variation</div>
                <div class="metric-value">{baseline_results.cv_npv_per_share:.2%}</div>
            </div>
        </div>
"""

        if 'baseline_dividend_sustainability' in plot_images:
            html_content += f"""
        <div class="plot-container">
            <h3>Dividend Sustainability Distribution</h3>
            <img src="data:image/png;base64,{plot_images['baseline_dividend_sustainability']}" alt="Dividend Sustainability">
        </div>
"""

        if 'baseline_npv_distribution' in plot_images:
            html_content += f"""
        <div class="plot-container">
            <h3>NPV Distribution</h3>
            <img src="data:image/png;base64,{plot_images['baseline_npv_distribution']}" alt="NPV Distribution">
        </div>
"""

    # Multi-Scenario Analysis Section
    if scenario_results and len(scenario_results) > 0:
        results_df = pd.DataFrame([{
            'scenario_idx': r['scenario_idx'],
            'starting_price_pct': r['starting_price_pct'],
            'starting_price': r['starting_price'],
            'mean_npv_per_share': r['mean_npv_per_share'],
            'median_npv_per_share': r['median_npv_per_share'],
            'mean_months_paid': r['mean_months_paid'],
            'std_npv_per_share': r['std_npv_per_share'],
            'min_npv_per_share': r['min_npv_per_share'],
            'max_npv_per_share': r['max_npv_per_share']
        } for r in scenario_results])

        # Format percentages and currency values for display
        results_df['starting_price_pct_formatted'] = results_df['starting_price_pct'].apply(lambda x: f"{x*100:.1f}%")
        results_df['mean_npv_per_share_formatted'] = results_df['mean_npv_per_share'].apply(lambda x: f"${x:,.2f}")
        results_df['mean_months_paid_formatted'] = results_df['mean_months_paid'].apply(lambda x: f"{x:.1f}")
        results_df['starting_price_formatted'] = results_df['starting_price'].apply(lambda x: f"${x:,.0f}")

        # Find the baseline scenario (closest to 0% starting price change)
        baseline_mask = results_df['starting_price_pct'].abs() < 1e-6  # Close to 0.0
        if not baseline_mask.any():
            # If no exact match, find the closest
            baseline_idx = results_df['starting_price_pct'].abs().idxmin()
            baseline_mask = results_df.index == baseline_idx

        baseline_npv = results_df[baseline_mask]['mean_npv_per_share'].iloc[0] if baseline_mask.any() else results_df['mean_npv_per_share'].iloc[len(results_df)//2]

        # Calculate new columns for the table
        results_df['npv_change_vs_baseline'] = ((results_df['mean_npv_per_share'] - baseline_npv) / baseline_npv * 100)
        results_df['npv_change_vs_baseline_formatted'] = results_df['npv_change_vs_baseline'].apply(lambda x: f"{x:+.2f}%")

        # Calculate elasticity: % change in NPV / % change in initial bitcoin price
        # Avoid division by zero for baseline scenario
        results_df['elasticity'] = np.where(
            results_df['starting_price_pct'] != 0,
            results_df['npv_change_vs_baseline'] / (results_df['starting_price_pct'] * 100),
            np.nan  # Will be handled as N/A for baseline
        )
        results_df['elasticity_formatted'] = results_df['elasticity'].apply(lambda x: f"{x:.2f}" if not np.isnan(x) else "N/A")

        html_content += f"""
    <div class="section">
        <h2>Multi-Scenario NPV Analysis</h2>
        <p>Analysis across {len(scenario_results)} Bitcoin starting price scenarios.</p>
"""

        if 'scenario_analysis' in plot_images:
            html_content += f"""
        <div class="plot-container">
            <h3>NPV vs Bitcoin Starting Price</h3>
            <img src="data:image/png;base64,{plot_images['scenario_analysis']}" alt="Scenario Analysis">
        </div>
"""

        if 'trend_slope' in plot_images and plot_images['trend_slope'] is not None:
            html_content += f"""
        <div class="summary-box">
            <h3>Trend Line Analysis</h3>
            <p><strong>Slope (Delta):</strong> ${plot_images['trend_slope']:.4f} per 1% change in Bitcoin starting price</p>
            <p><strong>Intercept:</strong> ${plot_images['trend_intercept']:.2f}</p>
            <p><strong>R-squared:</strong> {plot_images['trend_r_squared']:.1%}</p>
            <p>Interpretation: For every 1% increase in Bitcoin starting price, NPV increases by approximately ${plot_images['trend_slope']:.2f} per share.</p>
        </div>
"""

        html_content += f"""
        <h3>Detailed Scenario Results</h3>
        {results_df[['starting_price_pct_formatted', 'starting_price_formatted', 'mean_npv_per_share_formatted', 'npv_change_vs_baseline_formatted', 'elasticity_formatted']].rename(columns={'starting_price_pct_formatted': 'Starting Price Change', 'starting_price_formatted': 'Starting Price ($)', 'mean_npv_per_share_formatted': 'Mean NPV per Share ($)', 'npv_change_vs_baseline_formatted': '% Change in NPV vs Baseline', 'elasticity_formatted': 'NPV Elasticity vs Bitcoin Price'}).to_html(index=False, classes='', table_id='scenario-table')}
    </div>
"""

    # Sensitivity Analysis Section
    if sensitivity_results and len(sensitivity_results) > 0:
        sensitivity_df = pd.DataFrame([{
            'threshold_multiplier': r['threshold_multiplier'],
            'threshold_value': r['threshold_value'],
            'mean_npv_per_share': r['mean_npv_per_share'],
            'median_npv_per_share': r['median_npv_per_share'],
            'mean_months_paid': r['mean_months_paid'],
            'mean_accumulated_unpaid': r['mean_accumulated_unpaid'],
            'std_npv_per_share': r['std_npv_per_share']
        } for r in sensitivity_results])

        # Format percentages and currency values for display
        sensitivity_df['threshold_multiplier_formatted'] = sensitivity_df['threshold_multiplier'].apply(lambda x: f"{x:.2f}x")
        sensitivity_df['threshold_value_formatted'] = sensitivity_df['threshold_value'].apply(lambda x: f"${x:,.2f}")
        sensitivity_df['mean_npv_per_share_formatted'] = sensitivity_df['mean_npv_per_share'].apply(lambda x: f"${x:,.2f}")
        sensitivity_df['mean_months_paid_formatted'] = sensitivity_df['mean_months_paid'].apply(lambda x: f"{x:.1f}")
        sensitivity_df['mean_accumulated_unpaid_formatted'] = sensitivity_df['mean_accumulated_unpaid'].apply(lambda x: f"${x:,.2f}")
        html_content += f"""
    <div class="section">
        <h2>Sensitivity Analysis: Dividend Suspension Threshold</h2>
        <p>Analysis of how different suspension threshold multipliers affect NPV and dividend sustainability.</p>
"""

        if 'sensitivity_analysis' in plot_images:
            html_content += f"""
        <div class="plot-container">
            <h3>Sensitivity Analysis Plots</h3>
            <img src="data:image/png;base64,{plot_images['sensitivity_analysis']}" alt="Sensitivity Analysis">
        </div>
"""

        html_content += f"""
        <h3>Detailed Sensitivity Results</h3>
        {sensitivity_df[['threshold_multiplier_formatted', 'threshold_value_formatted', 'mean_npv_per_share_formatted', 'mean_months_paid_formatted']].rename(columns={'threshold_multiplier_formatted': 'Threshold Multiplier', 'threshold_value_formatted': 'Threshold Value ($)', 'mean_npv_per_share_formatted': 'Mean NPV per Share ($)', 'mean_months_paid_formatted': 'Mean Months Paid'}).to_html(index=False, classes='', table_id='sensitivity-table')}

        <div class="summary-box">
            <h3>Sensitivity Summary</h3>
            <p><strong>NPV Range:</strong> ${sensitivity_df['mean_npv_per_share'].min():,.2f} to ${sensitivity_df['mean_npv_per_share'].max():,.2f}</p>
            <p><strong>NPV Range Span:</strong> ${sensitivity_df['mean_npv_per_share'].max() - sensitivity_df['mean_npv_per_share'].min():,.2f}</p>
        </div>
    </div>
"""

    # Dividend Rate Sensitivity Analysis Section
    if dividend_rate_sensitivity_results and len(dividend_rate_sensitivity_results) > 0:
        dividend_rate_sensitivity_df = pd.DataFrame([{
            'dividend_rate': r['dividend_rate'],
            'dividend_rate_change_pct': r['dividend_rate_change_pct'],
            'mean_npv_per_share': r['mean_npv_per_share'],
            'median_npv_per_share': r['median_npv_per_share'],
            'mean_months_paid': r['mean_months_paid'],
            'mean_accumulated_unpaid': r['mean_accumulated_unpaid'],
            'std_npv_per_share': r['std_npv_per_share']
        } for r in dividend_rate_sensitivity_results])

        # Format percentages and currency values for display
        dividend_rate_sensitivity_df['dividend_rate_formatted'] = dividend_rate_sensitivity_df['dividend_rate'].apply(lambda x: f"{x:.2%}")
        dividend_rate_sensitivity_df['dividend_rate_change_pct_formatted'] = dividend_rate_sensitivity_df['dividend_rate_change_pct'].apply(lambda x: f"{x:+.2f}%")
        dividend_rate_sensitivity_df['mean_npv_per_share_formatted'] = dividend_rate_sensitivity_df['mean_npv_per_share'].apply(lambda x: f"${x:,.2f}")
        dividend_rate_sensitivity_df['mean_months_paid_formatted'] = dividend_rate_sensitivity_df['mean_months_paid'].apply(lambda x: f"{x:.1f}")
        dividend_rate_sensitivity_df['mean_accumulated_unpaid_formatted'] = dividend_rate_sensitivity_df['mean_accumulated_unpaid'].apply(lambda x: f"${x:,.2f}")

        html_content += f"""
    <div class="section">
        <h2>Sensitivity Analysis: Dividend Rate</h2>
        <p>Analysis of how different dividend rates affect NPV and dividend sustainability.</p>
"""

        if 'dividend_rate_sensitivity_analysis' in plot_images:
            html_content += f"""
        <div class="plot-container">
            <h3>Dividend Rate Sensitivity Analysis Plots</h3>
            <img src="data:image/png;base64,{plot_images['dividend_rate_sensitivity_analysis']}" alt="Dividend Rate Sensitivity Analysis">
        </div>
"""

        html_content += f"""
        <h3>Detailed Dividend Rate Sensitivity Results</h3>
        {dividend_rate_sensitivity_df[['dividend_rate_formatted', 'dividend_rate_change_pct_formatted', 'mean_npv_per_share_formatted', 'mean_months_paid_formatted']].rename(columns={'dividend_rate_formatted': 'Dividend Rate', 'dividend_rate_change_pct_formatted': '% Change from Baseline', 'mean_npv_per_share_formatted': 'Mean NPV per Share ($)', 'mean_months_paid_formatted': 'Mean Months Paid'}).to_html(index=False, classes='', table_id='dividend-rate-sensitivity-table')}

        <div class="summary-box">
            <h3>Dividend Rate Sensitivity Summary</h3>
            <p><strong>NPV Range:</strong> ${dividend_rate_sensitivity_df['mean_npv_per_share'].min():,.2f} to ${dividend_rate_sensitivity_df['mean_npv_per_share'].max():,.2f}</p>
            <p><strong>NPV Range Span:</strong> ${dividend_rate_sensitivity_df['mean_npv_per_share'].max() - dividend_rate_sensitivity_df['mean_npv_per_share'].min():,.2f}</p>
            <p><strong>Rate Range:</strong> {dividend_rate_sensitivity_df['dividend_rate'].min():.2%} to {dividend_rate_sensitivity_df['dividend_rate'].max():.2%}</p>
        </div>
    </div>
"""

    # BTC Credit Sensitivity Analysis Section
    if btc_credit_sensitivity_results and len(btc_credit_sensitivity_results) > 0:
        btc_credit_sensitivity_df = pd.DataFrame([{
            'btc_credit_ratio': r['btc_credit_ratio'],
            'btc_holdings': r['btc_holdings'],
            'mean_npv_per_share': r['mean_npv_per_share'],
            'median_npv_per_share': r['median_npv_per_share'],
            'mean_months_paid': r['mean_months_paid'],
            'mean_accumulated_unpaid': r['mean_accumulated_unpaid'],
            'std_npv_per_share': r['std_npv_per_share'],
            'npv_per_additional_btc': r['npv_per_additional_btc']
        } for r in btc_credit_sensitivity_results])

        # Format percentages and currency values for display
        btc_credit_sensitivity_df['btc_credit_ratio_formatted'] = btc_credit_sensitivity_df['btc_credit_ratio'].apply(lambda x: f"{x:.4f}x")
        btc_credit_sensitivity_df['btc_holdings_formatted'] = btc_credit_sensitivity_df['btc_holdings'].apply(lambda x: f"{x:,.0f} BTC")
        btc_credit_sensitivity_df['mean_npv_per_share_formatted'] = btc_credit_sensitivity_df['mean_npv_per_share'].apply(lambda x: f"${x:,.2f}")
        btc_credit_sensitivity_df['mean_months_paid_formatted'] = btc_credit_sensitivity_df['mean_months_paid'].apply(lambda x: f"{x:.1f}")
        btc_credit_sensitivity_df['mean_accumulated_unpaid_formatted'] = btc_credit_sensitivity_df['mean_accumulated_unpaid'].apply(lambda x: f"${x:,.2f}")
        btc_credit_sensitivity_df['npv_per_additional_btc_formatted'] = btc_credit_sensitivity_df['npv_per_additional_btc'].apply(lambda x: f"{x:.2f}")

        html_content += f"""
    <div class="section">
        <h2>Sensitivity Analysis: BTC Credit</h2>
        <p>Analysis of how different adjusted BTC credit ratios (including cash position) affect NPV and dividend sustainability.</p>
"""

        if 'btc_credit_sensitivity_analysis' in plot_images:
            html_content += f"""
        <div class="plot-container">
            <h3>BTC Credit Sensitivity Analysis Plots</h3>
            <img src="data:image/png;base64,{plot_images['btc_credit_sensitivity_analysis']}" alt="BTC Credit Sensitivity Analysis">
        </div>
"""

        html_content += f"""
        <h3>Detailed BTC Credit Sensitivity Results</h3>
        {btc_credit_sensitivity_df[['btc_credit_ratio_formatted', 'btc_holdings_formatted', 'mean_npv_per_share_formatted', 'mean_months_paid_formatted', 'npv_per_additional_btc_formatted']].rename(columns={'btc_credit_ratio_formatted': 'BTC Credit Ratio', 'btc_holdings_formatted': 'BTC Holdings', 'mean_npv_per_share_formatted': 'Mean NPV per Share ($)', 'mean_months_paid_formatted': 'Mean Months Paid', 'npv_per_additional_btc_formatted': 'NPV % Change / BTC % Change'}).to_html(index=False, classes='', table_id='btc-credit-sensitivity-table')}

        <div class="summary-box">
            <h3>BTC Credit Sensitivity Summary</h3>
            <p><strong>NPV Range:</strong> ${btc_credit_sensitivity_df['mean_npv_per_share'].min():,.2f} to ${btc_credit_sensitivity_df['mean_npv_per_share'].max():,.2f}</p>
            <p><strong>NPV Range Span:</strong> ${btc_credit_sensitivity_df['mean_npv_per_share'].max() - btc_credit_sensitivity_df['mean_npv_per_share'].min():,.2f}</p>
            <p><strong>BTC Credit Range:</strong> {btc_credit_sensitivity_df['btc_credit_ratio'].min():.1f}x to {btc_credit_sensitivity_df['btc_credit_ratio'].max():.1f}x</p>
        </div>
    </div>
"""

    html_content += """
</body>
</html>
"""

    with open(output_file, 'w') as f:
        f.write(html_content)

    print(f"✓ HTML report saved to: {output_file}")


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_results_from_json(json_file: str) -> Dict[str, Any]:
    """Load analysis results from JSON file."""
    with open(json_file, 'r') as f:
        return json.load(f)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Generate HTML report from JSON results."""
    parser = argparse.ArgumentParser(description='Generate HTML report from SATA valuation JSON results')
    parser.add_argument('--input', '-i', default=str(DEFAULT_OUTPUT_DIR / 'sata_valuation_results.json'),
                       help=f'Input JSON results file from sata_valuation.py (default: {DEFAULT_OUTPUT_DIR / "sata_valuation_results.json"})')
    parser.add_argument('--output', '-o', default=str(REPORTS_DIR / 'sata_valuation_report.html'),
                       help=f'Output HTML report file (default: {REPORTS_DIR / "sata_valuation_report.html"})')

    args = parser.parse_args()

    ensure_output_dirs()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # Validate input file exists
    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input JSON file not found: {args.input}")

    print(f"Loading results from: {args.input}")
    results = load_results_from_json(args.input)

    # Extract data from results
    config_dict = results['configuration']
    baseline_results = results['baseline_results']
    scenario_results = results['scenario_results']
    sensitivity_results = results['sensitivity_results']
    dividend_rate_sensitivity_results = results.get('dividend_rate_sensitivity_results', [])
    btc_credit_sensitivity_results = results.get('btc_credit_sensitivity_results', [])
    plot_images = results['plot_images']

    # Convert dict results back to objects for HTML generation
    # Note: This is a simplified approach - in production you'd want proper deserialization
    class SimpleResults:
        def __init__(self, data):
            for key, value in data.items():
                setattr(self, key, value)

    baseline_results_obj = SimpleResults(baseline_results) if baseline_results else None

    print(f"Generating HTML report: {args.output}")
    generate_html_report(
        config_dict=config_dict,
        baseline_results=baseline_results_obj,
        scenario_results=scenario_results,
        sensitivity_results=sensitivity_results,
        dividend_rate_sensitivity_results=dividend_rate_sensitivity_results,
        btc_credit_sensitivity_results=btc_credit_sensitivity_results,
        plot_images=plot_images,
        output_file=args.output
    )


if __name__ == '__main__':
    main()
