#!/usr/bin/env python3
"""
Fetch all live data and save JSON under output/ (single entry point for the data pipeline).

A full run (default) also fetches MSTR treasury (strategy.com) and ASST/SATA
(strategytracker.com). Use ``--only`` or ``--skip-*`` to fetch a subset.

Network responses are cached for 1 hour under output/cache/ (see data_cache.py).
Use --force-refresh to bypass the cache for a run.

This script fetches:
- Current MSTR stock price and options chain data
- Current STRC preferred price and options chain data
- Current IBIT stock price and options chain data
- BTC-per-share ratio constant for IBIT
- BTC historical price data and monthly returns
- U.S. Treasury discount curve (FRED DGS yields + bootstrap via `fetch_treasury_zero_yieldcurve.py`) to yield_curve.json
- Saves JSON files under `output/` by default (override with `--output-dir`): mstr_data.json, mstr_options.json, strc_data.json, strc_options.json, ibit_data.json, ibit_options.json, btc_historical_data.json, and yield_curve.json
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from fetch_treasury_zero_yieldcurve import (
    TreasuryZeroCurve,
    build_treasury_zero_curve,
    save_yield_curve_fallback_cache,
)
from data_cache import (
    begin_cache_tracking,
    get_or_fetch,
    is_fresh,
    read_cache,
    record_cache_hit,
    run_cache_hits,
    run_fresh_fetches,
    write_cache,
)
from strc_paths import OUTPUT_DIR, YIELD_CURVE_FALLBACK_PATH, ensure_output_dirs
from fetch_yahoo import load_btc_spot, yahoo_spot_price

# Constants
BTC_PER_SHARE = 22.69 / 40000  # BTC per IBIT share ratio

YIELD_CURVE_CACHE_KEY = "treasury_yield_curve"
MARKET_CACHE_KEYS: dict[str, tuple[str, ...]] = {
    "mstr": ("yahoo_history_MSTR_1d", "yahoo_options_MSTR"),
    "strc": ("yahoo_history_STRC_1d", "yahoo_options_STRC", "strategy_com_home"),
    "ibit": ("yahoo_history_IBIT_1d", "yahoo_options_IBIT", "yahoo_history_BTC-USD_1d"),
}


def _load_ticker_json(output_dir: Path, ticker: str) -> dict:
    with (output_dir / f"{ticker}_data.json").open() as f:
        return json.load(f)


def _market_inputs_unchanged(ticker: str, *, force_refresh: bool) -> bool:
    if force_refresh:
        return False
    keys = MARKET_CACHE_KEYS.get(ticker)
    if not keys:
        return False
    hits = run_cache_hits()
    return all(k in hits for k in keys)


def _maybe_keep_cached_ticker_files(
    ticker: str,
    output_dir: Path,
    *,
    force_refresh: bool,
) -> dict | None:
    """Return existing JSON when all inputs were cache hits and output files exist."""
    if not _market_inputs_unchanged(ticker, force_refresh=force_refresh):
        return None
    data_path = output_dir / f"{ticker}_data.json"
    if not data_path.is_file():
        return None
    print(f"\n   ✓ {ticker.upper()} unchanged (cache) — keeping existing files")
    return _load_ticker_json(output_dir, ticker)


def _tickers_skip_enrichment(
    tickers: tuple[str, ...],
    output_dir: Path,
    *,
    force_refresh: bool,
    require_yield_curve_hit: bool = True,
) -> frozenset[str]:
    if force_refresh:
        return frozenset()
    if require_yield_curve_hit and YIELD_CURVE_CACHE_KEY in run_fresh_fetches():
        return frozenset()
    from ibit_option_deltas import is_options_chain_enriched

    skip: set[str] = set()
    for ticker in tickers:
        if not _market_inputs_unchanged(ticker, force_refresh=force_refresh):
            continue
        if is_options_chain_enriched(output_dir / f"{ticker}_data.json"):
            skip.add(ticker)
    return frozenset(skip)

def fetch_options_chain(ticker, ticker_name, *, force_refresh: bool = False):
    """Helper function to fetch options chain data for a ticker"""
    cache_key = f"yahoo_options_{ticker_name}"

    def fetch():
        options_data = {}
        expirations = []

        try:
            expirations = list(ticker.options)
        except Exception as e:
            print(f"   ✗ Error fetching expirations for {ticker_name}: {e}")
            return {"options_data": options_data, "expirations": expirations}

        if len(expirations) > 0:
            print(f"   ✓ Found {len(expirations)} expiration dates")
            print(f"   First 5 expirations: {expirations[:5]}")
        else:
            print(f"   ⚠ No options data available for {ticker_name}")
            return {"options_data": options_data, "expirations": expirations}

        print(f"   Fetching options chain data for {len(expirations)} expirations...")
        for i, exp_str in enumerate(expirations):
            try:
                opt_chain = ticker.option_chain(exp_str)

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

        return {"options_data": options_data, "expirations": expirations}

    cached = get_or_fetch(cache_key, fetch, force_refresh=force_refresh)
    return cached["options_data"], cached["expirations"]


def fetch_mstr_data(output_dir: Path, *, force_refresh: bool = False):
    """Fetch MSTR stock price and options data"""
    
    print("\n" + "="*70)
    print("FETCHING MSTR DATA")
    print("="*70)
    
    # Get MSTR ticker
    mstr = yf.Ticker("MSTR")
    
    print("\n1. Fetching MSTR stock price...")
    current_price = yahoo_spot_price("MSTR", force_refresh=force_refresh)
    if current_price is not None:
        print(f"   ✓ Current MSTR Price: ${current_price:,.2f}")
    else:
        print("   ⚠ Could not fetch price data")
    
    # Fetch options data
    print("\n2. Fetching MSTR options expirations...")
    options_data, expirations = fetch_options_chain(mstr, "MSTR", force_refresh=force_refresh)
    
    # Prepare output data
    output_data = {
        'timestamp': datetime.now().isoformat(),
        'current_price': current_price,
        'expirations': expirations,
        'num_expirations': len(expirations),
        'options_data': options_data
    }
    
    kept = _maybe_keep_cached_ticker_files("mstr", output_dir, force_refresh=force_refresh)
    if kept is not None:
        return kept

    print("\n3. Saving MSTR data to files...")

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


def fetch_strc_data(output_dir: Path, *, force_refresh: bool = False):
    """Fetch STRC preferred price and options data"""

    from fetch_mstr_treasury import fetch_strc_metrics_from_strategy

    print("\n" + "=" * 70)
    print("FETCHING STRC DATA")
    print("=" * 70)

    print("\n1. Fetching STRC metrics from strategy.com...")
    strc_metrics = fetch_strc_metrics_from_strategy(force_refresh=force_refresh)

    strc = yf.Ticker("STRC")

    print("\n2. Fetching STRC price (Yahoo)...")
    current_price = yahoo_spot_price("STRC", force_refresh=force_refresh)
    if current_price is not None:
        print(f"   ✓ Current STRC Price: ${current_price:,.2f}")
    else:
        print("   ⚠ Could not fetch price data")

    print("\n3. Fetching STRC options expirations...")
    options_data, expirations = fetch_options_chain(strc, "STRC", force_refresh=force_refresh)

    output_data = {
        "timestamp": datetime.now().isoformat(),
        "current_price": current_price,
        "expirations": expirations,
        "num_expirations": len(expirations),
        "options_data": options_data,
    }

    if strc_metrics:
        output_data["strategy_metrics"] = strc_metrics
        div_yield = strc_metrics.get("dividend_rate")
        if div_yield is not None:
            output_data["dividend_yield"] = div_yield
            print(f"\n   ✓ STRC dividend yield: {div_yield:.2%}")
    else:
        print("\n   ⚠ STRC website metrics unavailable")

    kept = _maybe_keep_cached_ticker_files("strc", output_dir, force_refresh=force_refresh)
    if kept is not None:
        return kept

    print("\n4. Saving STRC data to files...")
    data_file = output_dir / "strc_data.json"
    with open(data_file, "w") as f:
        json.dump(output_data, f, indent=2)
    print(f"   ✓ Saved to {data_file}")

    options_file = output_dir / "strc_options.json"
    with open(options_file, "w") as f:
        json.dump(options_data, f, indent=2)
    print(f"   ✓ Saved to {options_file}")

    return output_data


def fetch_ibit_data(output_dir: Path, *, force_refresh: bool = False):
    """Fetch IBIT stock price and options data"""
    
    print("\n" + "="*70)
    print("FETCHING IBIT DATA")
    print("="*70)
    
    # Get IBIT ticker
    ibit = yf.Ticker("IBIT")
    
    print("\n1. Fetching IBIT stock price...")
    current_price = yahoo_spot_price("IBIT", force_refresh=force_refresh)
    if current_price is not None:
        print(f"   ✓ Current IBIT Price: ${current_price:,.2f}")
    else:
        print("   ⚠ Could not fetch price data")

    print("\n2. Fetching BTC price...")
    btc_price, btc_price_source = load_btc_spot(
        output_dir, force_refresh=force_refresh, log=False, return_source=True
    )
    if btc_price_source != "Yahoo BTC-USD (live)" and current_price is not None:
        # BTC-USD ticker failed but we already have a live IBIT quote — derive an
        # accurate implied BTC price from it instead of using a stale/fallback price.
        btc_price = current_price / BTC_PER_SHARE
        print(f"   ⚠ BTC-USD fetch unavailable ({btc_price_source}); derived from live IBIT quote: ${btc_price:,.2f}")
    else:
        print(f"   ✓ BTC price: ${btc_price:,.2f} ({btc_price_source})")

    # Fetch options data
    print("\n3. Fetching IBIT options expirations...")
    options_data, expirations = fetch_options_chain(ibit, "IBIT", force_refresh=force_refresh)
    
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
    
    kept = _maybe_keep_cached_ticker_files("ibit", output_dir, force_refresh=force_refresh)
    if kept is not None:
        return kept

    print("\n4. Saving IBIT data to files...")

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


def _load_yield_curve_json(path: Path) -> dict | None:
    """Return yield_curve.json payload when it looks like a bootstrapped curve."""
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("as_of_date") or payload.get("pillars_years"):
        return payload
    return None


def fetch_treasury_yield_curve(
    output_path: str | Path = "yield_curve.json",
    *,
    force_refresh: bool = False,
) -> dict | None:
    """
    Fetch FRED constant-maturity Treasury yields and bootstrap discount factors;
    save to yield_curve.json for ibit_option_deltas.py and notebooks.
    """
    print("\n" + "=" * 70)
    print("FETCHING TREASURY YIELD CURVE (FRED → bootstrap)")
    print("=" * 70)

    def fetch() -> dict:
        curve = build_treasury_zero_curve(session=requests.Session())
        payload = {"timestamp": datetime.now().isoformat()}
        payload.update(curve.to_json_dict())
        return payload

    outp = Path(output_path)

    def _persist_live(payload: dict) -> None:
        outp.parent.mkdir(parents=True, exist_ok=True)
        with open(outp, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"   ✓ Saved to {outp}")

    try:
        payload = get_or_fetch("treasury_yield_curve", fetch, force_refresh=force_refresh)
        print(f"\n   ✓ FRED observation as-of: {payload.get('as_of_date', 'N/A')}")
        _persist_live(payload)
        # Refresh the tracked (committed) fallback only on a genuine FRED
        # fetch — not on a 1h cache hit — so last-known-good stays current.
        if YIELD_CURVE_CACHE_KEY in run_fresh_fetches():
            try:
                curve = TreasuryZeroCurve.from_saved_dict(payload)
                save_yield_curve_fallback_cache(curve, YIELD_CURVE_FALLBACK_PATH)
                print(f"   ✓ Updated fallback cache: {YIELD_CURVE_FALLBACK_PATH.name}")
            except Exception as cache_err:
                print(f"   ⚠ Could not update fallback cache: {cache_err}")
        return payload
    except Exception as e:
        print(f"\n   ✗ Could not fetch fresh yield curve: {e}")
        for stale_path, label in (
            (outp, str(outp)),
            (YIELD_CURVE_FALLBACK_PATH, YIELD_CURVE_FALLBACK_PATH.name),
        ):
            stale = _load_yield_curve_json(stale_path)
            if stale is None:
                continue
            print(f"   ✓ Using {label} (as-of {stale.get('as_of_date', 'N/A')})")
            _persist_live(stale)
            write_cache(YIELD_CURVE_CACHE_KEY, stale)
            record_cache_hit(YIELD_CURVE_CACHE_KEY)
            return stale
        print("   ⚠ No yield_curve.json or fallback — option deltas will use flat 4.2% or retry FRED live")
        return None


def fetch_btc_historical_data(
    historical_period='max',
    output_dir: Path | None = None,
    *,
    force_refresh: bool = False,
):
    """Fetch BTC historical price data and calculate monthly returns"""

    print("\n" + "="*70)
    print("FETCHING BTC HISTORICAL DATA")
    print("="*70)
    print(f"Fetching historical Bitcoin data for period: {historical_period}...")

    def fetch() -> dict:
        btc_ticker = yf.Ticker("BTC-USD")
        btc_data = btc_ticker.history(period=historical_period)
        btc_prices = btc_data['Close'].dropna()
        btc_prices_monthly = btc_prices.resample('ME').last()
        btc_returns = np.log(btc_prices_monthly / btc_prices_monthly.shift(1)).dropna()
        return {
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

    cache_key = "yahoo_btc_historical_max" if historical_period == "max" else f"yahoo_btc_historical_{historical_period}"
    out = output_dir or OUTPUT_DIR
    data_file = out / "btc_historical_data.json"

    fetched = get_or_fetch(cache_key, fetch, force_refresh=force_refresh)

    if not force_refresh and cache_key in run_cache_hits() and data_file.is_file():
        print("\n   ✓ BTC historical unchanged (cache) — keeping existing file")
        with data_file.open() as f:
            return json.load(f)

    print(f"\nData fetched successfully!")
    print(f"Date range: {fetched['date_range']['start']} to {fetched['date_range']['end']}")
    print(f"Daily observations: {fetched['daily_observations']:,}")
    print(f"Monthly observations: {fetched['monthly_observations']:,}")
    print(f"Current Bitcoin price: ${fetched['current_price']:,.2f}")

    output_data = {
        'timestamp': datetime.now().isoformat(),
        **fetched,
    }

    print("\nSaving BTC historical data to file...")
    out.mkdir(parents=True, exist_ok=True)
    with open(data_file, 'w') as f:
        json.dump(output_data, f, indent=2)
    print(f"   ✓ Saved to {data_file}")

    return output_data


def _run_fetch_tasks(
    tasks: list[tuple[str, callable]],
    *,
    max_workers: int | None = None,
) -> dict[str, object]:
    """Run independent fetch callables in parallel; return {name: result}."""
    if not tasks:
        return {}
    if len(tasks) == 1:
        name, fn = tasks[0]
        return {name: fn()}

    workers = min(max_workers or len(tasks), len(tasks))
    print(f"\nRunning {len(tasks)} fetches in parallel ({workers} workers)...")
    results: dict[str, object] = {}
    errors: list[tuple[str, BaseException]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_name = {pool.submit(fn): name for name, fn in tasks}
        for fut in as_completed(future_to_name):
            name = future_to_name[fut]
            try:
                results[name] = fut.result()
            except Exception as exc:
                errors.append((name, exc))
                print(f"\n✗ {name} fetch failed: {exc}", file=sys.stderr)

    if errors:
        failed = ", ".join(n for n, _ in errors)
        raise RuntimeError(f"Fetch failed for: {failed}") from errors[0][1]

    return results


def fetch_all_data(
    output_dir: Path | None = None,
    *,
    only: str | None = None,
    skip_mstr_treasury: bool = False,
    skip_asst: bool = False,
    skip_deltas: bool = False,
    force_refresh: bool = False,
):
    """Fetch all market + treasury data, then enrich options with delta/IV."""
    begin_cache_tracking()
    out = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    print("="*70)
    print("FETCHING MARKET DATA")
    print("="*70)
    print(f"\nOutput directory: {out}")
    print(f"\nBTC_PER_SHARE constant: {BTC_PER_SHARE:.6f}")
    print(f"(Calculated as: 22.69 / 40000)")
    
    mstr_data = ibit_data = strc_data = btc_data = None
    kw = {"force_refresh": force_refresh}

    market_tasks: list[tuple[str, callable]] = []
    if only is None or only == "mstr":
        market_tasks.append(("mstr", lambda: fetch_mstr_data(out, **kw)))
    if only is None or only == "strc":
        market_tasks.append(("strc", lambda: fetch_strc_data(out, **kw)))
    if only is None or only == "ibit":
        market_tasks.append(("ibit", lambda: fetch_ibit_data(out, **kw)))
    if only is None:
        market_tasks.append(("btc", lambda: fetch_btc_historical_data(output_dir=out, **kw)))
        market_tasks.append(
            ("yield_curve", lambda: fetch_treasury_yield_curve(out / "yield_curve.json", **kw))
        )
        if not skip_asst:
            market_tasks.append(
                (
                    "asst",
                    lambda: __import__("fetch_asst_api").fetch_asst_data(
                        output_path=out / "treasury_extracted_data.json", **kw
                    ),
                )
            )
        if not skip_mstr_treasury:
            from fetch_mstr_treasury import fetch_and_save_mstr_treasury
            market_tasks.append(
                ("mstr_treasury", lambda: fetch_and_save_mstr_treasury(output_dir=out, **kw))
            )

    market_results = _run_fetch_tasks(market_tasks)
    mstr_data = market_results.get("mstr")
    strc_data = market_results.get("strc")
    ibit_data = market_results.get("ibit")
    btc_data = market_results.get("btc")

    # Normalize ASST/MSTR common-share dilution into share_dilution.json
    # (and patch treasury / mstr enriched share fields for rNAV denominators).
    if only is None and (not skip_asst or not skip_mstr_treasury):
        try:
            from fetch_share_dilution import build_share_dilution

            build_share_dilution(
                out,
                force_refresh=force_refresh,
                asst_only=skip_mstr_treasury and not skip_asst,
                mstr_only=skip_asst and not skip_mstr_treasury,
            )
        except Exception as e:
            print(f"\n⚠ share dilution refresh failed: {e}")

    if not skip_deltas:
        from ibit_option_deltas import enrich_all_option_chains

        if only is None:
            delta_tickers = ("mstr", "strc", "ibit")
        else:
            delta_tickers = (only,)
        skip_enrich = _tickers_skip_enrichment(
            delta_tickers,
            out,
            force_refresh=force_refresh,
            require_yield_curve_hit=(only is None),
        )
        enrich_all_option_chains(
            out,
            tickers=delta_tickers,
            yield_curve_path=out / "yield_curve.json",
            quiet=True,
            parallel=True,
            skip_tickers=skip_enrich,
        )

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if mstr_data:
        print(f"\nMSTR:")
        print(f"  Current Price: ${mstr_data['current_price']:,.2f}" if mstr_data["current_price"] else "  Current Price: N/A")
        print(f"  Expirations: {mstr_data['num_expirations']}")
        print(f"  Total Options Contracts: {sum(opt['num_calls'] + opt['num_puts'] for opt in mstr_data['options_data'].values())}")

    if strc_data:
        print(f"\nSTRC:")
        print(f"  Current Price: ${strc_data['current_price']:,.2f}" if strc_data["current_price"] else "  Current Price: N/A")
        print(f"  Expirations: {strc_data['num_expirations']}")
        print(f"  Total Options Contracts: {sum(opt['num_calls'] + opt['num_puts'] for opt in strc_data['options_data'].values())}")

    if ibit_data:
        print(f"\nIBIT:")
        print(f"  Current Price: ${ibit_data['current_price']:,.2f}" if ibit_data["current_price"] else "  Current Price: N/A")
        print(f"  BTC Price: ${ibit_data['btc_price']:,.2f}" if ibit_data.get("btc_price") else "  BTC Price: N/A")
        print(f"  BTC per Share: {ibit_data['btc_per_share']:.6f}")
        print(f"  Expirations: {ibit_data['num_expirations']}")
        print(f"  Total Options Contracts: {sum(opt['num_calls'] + opt['num_puts'] for opt in ibit_data['options_data'].values())}")

    if btc_data:
        print(f"\nBTC Historical:")
        print(f"  Current Price: ${btc_data['current_price']:,.2f}")
        print(f"  Date Range: {btc_data['date_range']['start']} to {btc_data['date_range']['end']}")
        print(f"  Daily Observations: {btc_data['daily_observations']:,}")
        print(f"  Monthly Observations: {btc_data['monthly_observations']:,}")

    print(f"\nData Files (under {out}):")
    for name in (
        "mstr_data.json", "mstr_options.json",
        "strc_data.json", "strc_options.json",
        "ibit_data.json", "ibit_options.json",
        "btc_historical_data.json", "yield_curve.json",
        "mstr_strategy_raw.json", "mstr_treasury_extracted_data.json",
        "mstr_enriched_data.json", "treasury_extracted_data.json",
    ):
        print(f"  - {name}")
    print("=" * 70)

    return mstr_data, ibit_data, strc_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch market data for STRC Sim")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=f"Directory for JSON outputs (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--only",
        choices=("mstr", "strc", "ibit"),
        default=None,
        help="Fetch a single ticker chain (skips BTC history, yield curve, treasury)",
    )
    parser.add_argument(
        "--skip-mstr-treasury",
        action="store_true",
        help="Skip strategy.com MSTR treasury (mstr_treasury_extracted_data.json)",
    )
    parser.add_argument(
        "--skip-asst",
        action="store_true",
        help="Skip ASST/SATA strategytracker fetch (treasury_extracted_data.json)",
    )
    parser.add_argument(
        "--skip-deltas",
        action="store_true",
        help="Skip ibit_option_deltas enrichment (delta/IV/gamma on option chains)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass cache and refetch all network data",
    )
    args = parser.parse_args()
    ensure_output_dirs()
    fetch_all_data(
        args.output_dir if args.output_dir is not None else OUTPUT_DIR,
        only=args.only,
        skip_mstr_treasury=args.skip_mstr_treasury,
        skip_asst=args.skip_asst,
        skip_deltas=args.skip_deltas,
        force_refresh=args.force_refresh,
    )

