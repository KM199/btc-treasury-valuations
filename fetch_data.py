#!/usr/bin/env python3
"""
Fetch MSTR, IBIT, BTCC, and BTC historical data and save to JSON files for use in notebooks.

This script fetches:
- Current MSTR stock price and options chain data
- Current IBIT stock price and options chain data
- BTC-per-share ratio constant for IBIT
- BTCC treasury data (Bitcoin holdings, cash, SATA preferred stock data) from treasury.strive.com
- BTC historical price data and monthly returns
- U.S. Treasury discount curve (FRED DGS yields + bootstrap via `fetch_treasury_zero_yieldcurve.py`) to yield_curve.json
- Saves JSON files under `output/` by default (override with `--output-dir`): mstr_data.json, mstr_options.json, ibit_data.json, ibit_options.json, btc_historical_data.json, and yield_curve.json
"""

import argparse
import json
import yfinance as yf
import pandas as pd
from datetime import datetime
from pathlib import Path
import requests
import re
import numpy as np

from fetch_treasury_zero_yieldcurve import build_treasury_zero_curve
from strc_paths import OUTPUT_DIR, ensure_output_dirs

# Constants
BTC_PER_SHARE = 22.69 / 40000  # BTC per IBIT share ratio

def fetch_options_chain(ticker, ticker_name):
    """Helper function to fetch options chain data for a ticker"""
    options_data = {}
    
    try:
        expirations = ticker.options
        if len(expirations) > 0:
            print(f"   ✓ Found {len(expirations)} expiration dates")
            print(f"   First 5 expirations: {expirations[:5]}")
        else:
            print(f"   ⚠ No options data available for {ticker_name}")
            return options_data, []
    except Exception as e:
        print(f"   ✗ Error fetching expirations for {ticker_name}: {e}")
        return options_data, []
    
    # Fetch options chain data for all expirations
    print(f"   Fetching options chain data for {len(expirations)} expirations...")
    for i, exp_str in enumerate(expirations):
        try:
            opt_chain = ticker.option_chain(exp_str)
            
            # Extract calls and puts
            calls_data = []
            puts_data = []
            
            if hasattr(opt_chain, 'calls') and len(opt_chain.calls) > 0:
                calls_df = opt_chain.calls
                for _, row in calls_df.iterrows():
                    calls_data.append({
                        'strike': float(row['strike']),
                        'bid': float(row.get('bid', 0)) if pd.notna(row.get('bid')) else 0,
                        'ask': float(row.get('ask', 0)) if pd.notna(row.get('ask')) else 0,
                        'lastPrice': float(row.get('lastPrice', 0)) if pd.notna(row.get('lastPrice')) else 0,
                        'volume': int(row.get('volume', 0)) if pd.notna(row.get('volume')) else 0,
                        'openInterest': int(row.get('openInterest', 0)) if pd.notna(row.get('openInterest')) else 0
                    })
            
            if hasattr(opt_chain, 'puts') and len(opt_chain.puts) > 0:
                puts_df = opt_chain.puts
                for _, row in puts_df.iterrows():
                    puts_data.append({
                        'strike': float(row['strike']),
                        'bid': float(row.get('bid', 0)) if pd.notna(row.get('bid')) else 0,
                        'ask': float(row.get('ask', 0)) if pd.notna(row.get('ask')) else 0,
                        'lastPrice': float(row.get('lastPrice', 0)) if pd.notna(row.get('lastPrice')) else 0,
                        'volume': int(row.get('volume', 0)) if pd.notna(row.get('volume')) else 0,
                        'openInterest': int(row.get('openInterest', 0)) if pd.notna(row.get('openInterest')) else 0
                    })
            
            options_data[exp_str] = {
                'calls': calls_data,
                'puts': puts_data,
                'num_calls': len(calls_data),
                'num_puts': len(puts_data)
            }
            
            if (i + 1) % 5 == 0 or i == len(expirations) - 1:
                print(f"      Processed {i+1}/{len(expirations)} expirations...")
                
        except Exception as e:
            print(f"      ⚠ Error processing {exp_str}: {e}")
            continue
    
    return options_data, expirations

def fetch_mstr_data(output_dir: Path):
    """Fetch MSTR stock price and options data"""
    
    print("\n" + "="*70)
    print("FETCHING MSTR DATA")
    print("="*70)
    
    # Get MSTR ticker
    mstr = yf.Ticker("MSTR")
    
    # Fetch current stock price
    print("\n1. Fetching MSTR stock price...")
    try:
        price_data = mstr.history(period="1d")
        if len(price_data) > 0:
            current_price = float(price_data['Close'].iloc[-1])
            print(f"   ✓ Current MSTR Price: ${current_price:,.2f}")
        else:
            print("   ⚠ Could not fetch price data")
            current_price = None
    except Exception as e:
        print(f"   ✗ Error fetching price: {e}")
        current_price = None
    
    # Fetch options data
    print("\n2. Fetching MSTR options expirations...")
    options_data, expirations = fetch_options_chain(mstr, "MSTR")
    
    # Prepare output data
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'current_price': current_price,
        'expirations': expirations,
        'num_expirations': len(expirations),
        'options_data': options_data
    }
    
    # Save to JSON files
    print("\n3. Saving MSTR data to files...")
    
    # Save main data file
    data_file = output_dir / 'mstr_data.json'
    with open(data_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    print(f"   ✓ Saved to {data_file}")
    
    # Save options data separately (larger file)
    options_file = output_dir / 'mstr_options.json'
    with open(options_file, 'w') as f:
        json.dump(options_data, f, indent=2)
    print(f"   ✓ Saved to {options_file}")
    
    return output_data

def fetch_ibit_data(output_dir: Path):
    """Fetch IBIT stock price and options data"""
    
    print("\n" + "="*70)
    print("FETCHING IBIT DATA")
    print("="*70)
    
    # Get IBIT ticker
    ibit = yf.Ticker("IBIT")
    
    # Fetch current stock price
    print("\n1. Fetching IBIT stock price...")
    try:
        price_data = ibit.history(period="1d")
        if len(price_data) > 0:
            current_price = float(price_data['Close'].iloc[-1])
            print(f"   ✓ Current IBIT Price: ${current_price:,.2f}")
        else:
            print("   ⚠ Could not fetch price data")
            current_price = None
    except Exception as e:
        print(f"   ✗ Error fetching price: {e}")
        current_price = None
    
    # Fetch BTC price
    print("\n2. Fetching BTC price...")
    try:
        btc_ticker = yf.Ticker("BTC-USD")
        btc_price_data = btc_ticker.history(period="1d")
        if len(btc_price_data) > 0:
            btc_price = float(btc_price_data['Close'].iloc[-1])
            print(f"   ✓ Current BTC Price: ${btc_price:,.2f}")
        else:
            # Calculate implied Bitcoin price from IBIT
            if current_price:
                btc_price = current_price / BTC_PER_SHARE
                print(f"   ✓ Implied BTC Price: ${btc_price:,.2f}")
            else:
                btc_price = None
                print("   ⚠ Could not calculate BTC price")
    except Exception as e:
        print(f"   ⚠ Error fetching BTC price: {e}")
        if current_price:
            btc_price = current_price / BTC_PER_SHARE
            print(f"   ✓ Implied BTC Price: ${btc_price:,.2f}")
        else:
            btc_price = None
    
    # Fetch options data
    print("\n3. Fetching IBIT options expirations...")
    options_data, expirations = fetch_options_chain(ibit, "IBIT")
    
    # Prepare output data
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'current_price': current_price,
        'btc_price': btc_price,
        'btc_per_share': BTC_PER_SHARE,
        'expirations': expirations,
        'num_expirations': len(expirations),
        'options_data': options_data
    }
    
    # Save to JSON files
    print("\n4. Saving IBIT data to files...")
    
    # Save main data file
    data_file = output_dir / 'ibit_data.json'
    with open(data_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    print(f"   ✓ Saved to {data_file}")
    
    # Save options data separately (larger file)
    options_file = output_dir / 'ibit_options.json'
    with open(options_file, 'w') as f:
        json.dump(options_data, f, indent=2)
    print(f"   ✓ Saved to {options_file}")
    
    return output_data


def fetch_treasury_yield_curve(output_path: str | Path = "yield_curve.json") -> dict | None:
    """
    Fetch FRED constant-maturity Treasury yields and bootstrap discount factors;
    save to yield_curve.json for ibit_option_deltas.py and notebooks.
    """
    print("\n" + "=" * 70)
    print("FETCHING TREASURY YIELD CURVE (FRED → bootstrap)")
    print("=" * 70)
    try:
        curve = build_treasury_zero_curve(session=requests.Session())
        payload = {"timestamp": datetime.now().isoformat()}
        payload.update(curve.to_json_dict())
        outp = Path(output_path)
        outp.parent.mkdir(parents=True, exist_ok=True)
        with open(outp, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"\n   ✓ FRED observation as-of: {curve.as_of_date}")
        print(f"   ✓ Saved to {outp}")
        return payload
    except Exception as e:
        print(f"\n   ✗ Could not build/save yield curve: {e}")
        return None


def fetch_btc_historical_data(historical_period='max', output_dir: Path | None = None):
    """Fetch BTC historical price data and calculate monthly returns"""

    print("\n" + "="*70)
    print("FETCHING BTC HISTORICAL DATA")
    print("="*70)
    print(f"Fetching historical Bitcoin data for period: {historical_period}...")

    # Fetch historical data
    btc_ticker = yf.Ticker("BTC-USD")
    btc_data = btc_ticker.history(period=historical_period)

    # Extract closing prices
    btc_prices = btc_data['Close'].dropna()

    # Calculate monthly returns
    btc_prices_monthly = btc_prices.resample('M').last()
    btc_returns = np.log(btc_prices_monthly / btc_prices_monthly.shift(1)).dropna()

    print(f"\nData fetched successfully!")
    print(f"Date range: {btc_prices.index[0].date()} to {btc_prices.index[-1].date()}")
    print(f"Daily observations: {len(btc_prices):,}")
    print(f"Monthly observations: {len(btc_returns):,}")
    print(f"Current Bitcoin price: ${btc_prices.iloc[-1]:,.2f}")

    # Prepare data for JSON serialization
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'historical_period': historical_period,
        'date_range': {
            'start': btc_prices.index[0].date().isoformat(),
            'end': btc_prices.index[-1].date().isoformat()
        },
        'daily_observations': len(btc_prices),
        'monthly_observations': len(btc_returns),
        'current_price': float(btc_prices.iloc[-1]),
        'daily_prices': {
            'dates': [date.date().isoformat() for date in btc_prices.index],
            'prices': [float(price) for price in btc_prices.values]
        },
        'monthly_returns': {
            'dates': [date.date().isoformat() for date in btc_returns.index],
            'returns': [float(ret) for ret in btc_returns.values]
        }
    }

    # Save to JSON file
    print("\nSaving BTC historical data to file...")
    out = output_dir or OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    data_file = out / 'btc_historical_data.json'
    with open(data_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    print(f"   ✓ Saved to {data_file}")

    return output_data

def fetch_all_data(output_dir: Path | None = None):
    """Fetch all data (MSTR, IBIT, and BTCC)"""
    out = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    print("="*70)
    print("FETCHING MARKET DATA")
    print("="*70)
    print(f"\nOutput directory: {out}")
    print(f"\nBTC_PER_SHARE constant: {BTC_PER_SHARE:.6f}")
    print(f"(Calculated as: 22.69 / 40000)")
    
    # Fetch MSTR data
    mstr_data = fetch_mstr_data(out)
    
    # Fetch IBIT data
    ibit_data = fetch_ibit_data(out)
    
    # Fetch BTC historical data
    btc_data = fetch_btc_historical_data(output_dir=out)

    fetch_treasury_yield_curve(out / "yield_curve.json")

    # Print summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"\nMSTR:")
    print(f"  Current Price: ${mstr_data['current_price']:,.2f}" if mstr_data['current_price'] else "  Current Price: N/A")
    print(f"  Expirations: {mstr_data['num_expirations']}")
    print(f"  Total Options Contracts: {sum(opt['num_calls'] + opt['num_puts'] for opt in mstr_data['options_data'].values())}")
    
    print(f"\nIBIT:")
    print(f"  Current Price: ${ibit_data['current_price']:,.2f}" if ibit_data['current_price'] else "  Current Price: N/A")
    print(f"  BTC Price: ${ibit_data['btc_price']:,.2f}" if ibit_data['btc_price'] else "  BTC Price: N/A")
    print(f"  BTC per Share: {ibit_data['btc_per_share']:.6f}")
    print(f"  Expirations: {ibit_data['num_expirations']}")
    print(f"  Total Options Contracts: {sum(opt['num_calls'] + opt['num_puts'] for opt in ibit_data['options_data'].values())}")

    print(f"\nBTC Historical:")
    print(f"  Current Price: ${btc_data['current_price']:,.2f}")
    print(f"  Date Range: {btc_data['date_range']['start']} to {btc_data['date_range']['end']}")
    print(f"  Daily Observations: {btc_data['daily_observations']:,}")
    print(f"  Monthly Observations: {btc_data['monthly_observations']:,}")

    print(f"\nData Files (under {out}):")
    print(f"  - mstr_data.json")
    print(f"  - mstr_options.json")
    print(f"  - ibit_data.json")
    print(f"  - ibit_options.json")
    print(f"  - btc_historical_data.json")
    print(f"  - yield_curve.json")
    print("="*70)
    
    return mstr_data, ibit_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch market data for STRC Sim")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Directory for JSON outputs (default: {OUTPUT_DIR})",
    )
    args = parser.parse_args()
    ensure_output_dirs()
    fetch_all_data(args.output_dir if args.output_dir is not None else OUTPUT_DIR)

