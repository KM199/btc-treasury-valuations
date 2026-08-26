#!/usr/bin/env python3
"""
Fetch ASST (Strive Asset Management / SATA) treasury data from data.strategytracker.com.

Network responses are cached for 1 hour under output/cache/ (see data_cache.py).
Use --force-refresh to bypass the cache for a run.

Also invoked by ``fetch_data.py`` on a full run (or run standalone):
  python fetch_asst_api.py
"""

import argparse
import json
import requests
from datetime import datetime
from pathlib import Path

from data_cache import get_or_fetch
from strc_paths import OUTPUT_DIR, ensure_output_dirs

_TRACKER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://treasury.strive.com/",
    "Origin": "https://treasury.strive.com",
}


def _fetch_json_url(url: str, timeout: float = 15) -> dict:
    response = requests.get(url, headers=_TRACKER_HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.json()


def fetch_strategytracker_company(
    ticker: str, *, force_refresh: bool = False, timeout: float = 20
) -> dict | None:
    """Return ``companies[TICKER]`` from data.strategytracker.com, or None."""
    ticker = ticker.upper()
    latest = get_or_fetch(
        "strategytracker_latest",
        lambda: _fetch_json_url("https://data.strategytracker.com/latest.json", timeout=10),
        force_refresh=force_refresh,
    )
    version = (latest or {}).get("version")
    if not version:
        return None
    payload = get_or_fetch(
        f"strategytracker_{ticker}_v{version}",
        lambda: _fetch_json_url(
            f"https://data.strategytracker.com/{ticker}.v{version}.json",
            timeout=timeout,
        ),
        force_refresh=force_refresh,
    )
    companies = (payload or {}).get("companies") or {}
    company = companies.get(ticker)
    return company if isinstance(company, dict) else None


def fetch_asst_data(output_path: Path | None = None, *, force_refresh: bool = False):
    """Fetch ASST company data from strategytracker API."""
    
    print("="*70)
    print("FETCHING ASST DATA (strategytracker.com)")
    print("="*70)
    
    # Step 1: Get latest version
    print("\n1. Fetching latest version...")
    latest_url = "https://data.strategytracker.com/latest.json"
    try:
        latest_data = get_or_fetch(
            "strategytracker_latest",
            lambda: _fetch_json_url(latest_url, timeout=10),
            force_refresh=force_refresh,
        )
        version = latest_data.get("version")
        print(f"   ✓ Version: {version}")
        print(f"   Previous versions: {latest_data.get('previous_versions', [])}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return None

    # Step 2: Fetch ASST data using the version
    print(f"\n2. Fetching ASST data (version: {version})...")
    ticker = "ASST"
    asst_url = f"https://data.strategytracker.com/{ticker}.v{version}.json"
    print(f"   URL: {asst_url}")

    try:
        data = get_or_fetch(
            f"strategytracker_{ticker}_v{version}",
            lambda: _fetch_json_url(asst_url, timeout=15),
            force_refresh=force_refresh,
        )
        print("   ✓ Successfully fetched data")

        companies = data.get("companies", {})
        asst = companies.get("ASST", {})

        if not asst:
            print(f"   ✗ ASST not found in companies. Available: {list(companies.keys())[:10]}")
            return None

        return extract_and_display_data(asst, data, output_path=output_path)
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def extract_and_display_data(asst, full_data, output_path: Path | None = None):
    """Extract and display all the target data"""
    
    print("\n" + "="*70)
    print("EXTRACTED DATA")
    print("="*70)
    
    # BTC Holdings
    processed = asst.get('processedMetrics', {})
    btc_holdings = processed.get('latestBtcBalance')
    
    # Cash
    cash = processed.get('latestCashBalance')
    
    # Market Comparison (EV, mcap, debt) - might not be in API response
    market_comp = asst.get('marketComparison', {})
    ev = market_comp.get('enterpriseValue') if market_comp else None
    mcap = market_comp.get('marketCap') if market_comp else None
    debt = processed.get('latestDebt')
    
    # Also check processedMetrics for market cap
    if not mcap:
        mcap = processed.get('currentMarketCap') or processed.get('marketCapBasic')
    
    # SATA Preferred Stock
    preferred_stocks = processed.get('preferredStocks', [])
    sata = preferred_stocks[0] if preferred_stocks and len(preferred_stocks) > 0 else {}
    
    # SATA shares might be wrong in sharesOutstanding - calculate from notional instead
    notional = sata.get('notionalUSD')
    shares = sata.get('sharesOutstanding')
    # Calculate correct shares from notional (par value is $100)
    if notional and notional > 0:
        shares_from_notional = int(notional / 100)  # $100 par value
        # Use calculated shares if sharesOutstanding seems wrong (too high)
        if shares and shares > 10000000:  # If shares > 10M, it's probably wrong
            shares = shares_from_notional
        elif not shares:
            shares = shares_from_notional
    ticker = sata.get('ticker', '')
    price = sata.get('price')
    dividend_rate = sata.get('dividendRate')
    effective_yield = sata.get('effectiveYield')
    
    # Display all data
    extracted = {}
    
    if btc_holdings:
        print(f"\n✓ BTC Holdings: {btc_holdings:,.2f} BTC")
        extracted['btc_holdings'] = float(btc_holdings)
    
    if cash:
        print(f"✓ Cash: ${cash:,.0f}")
        extracted['cash'] = float(cash)
    
    if ev:
        print(f"✓ Enterprise Value (EV): ${ev:,.0f}")
        extracted['ev'] = float(ev)
    
    if mcap:
        print(f"✓ Market Cap: ${mcap:,.0f}")
        extracted['mcap'] = float(mcap)
    elif processed.get('currentMarketCap'):
        mcap = processed.get('currentMarketCap')
        print(f"✓ Market Cap (from processedMetrics): ${mcap:,.0f}")
        extracted['mcap'] = float(mcap)
    
    if debt is not None:
        debt = float(debt)
        print(f"✓ Debt: ${debt:,.0f}")
        extracted['debt'] = debt
    
    if sata:
        print(f"\n✓ SATA Preferred Stock:")
        if ticker:
            print(f"  Ticker: {ticker}")
            extracted['sata_ticker'] = ticker
        
        if shares:
            print(f"  Shares Outstanding: {shares:,}")
            extracted['sata_shares'] = int(shares)
        
        if notional:
            print(f"  Notional (Par Value): ${notional:,.0f}")
            extracted['sata_notional'] = float(notional)
            # Calculate shares from notional if shares not available
            if not shares:
                calculated_shares = int(notional / 100)  # $100 par
                print(f"  Calculated Shares (from notional): {calculated_shares:,}")
                extracted['sata_shares_calculated'] = calculated_shares
        
        if price:
            print(f"  Current Price: ${price:.2f}")
            extracted['sata_price'] = float(price)
        
        if dividend_rate:
            print(f"  Dividend Rate: {dividend_rate:.2f}%")
            extracted['sata_dividend_rate'] = float(dividend_rate)
            # Calculate interest rate on par value
            
        if effective_yield:
            print(f"  Effective Yield: {effective_yield:.2f}%")
            extracted['sata_effective_yield'] = float(effective_yield)

    # Common-share dilution (warrants/options/RSUs) — excludes SATA (preferred claim)
    from fetch_share_dilution import extract_asst_dilution

    dil = extract_asst_dilution(
        processed, source="https://data.strategytracker.com/"
    )
    if dil.get("basic_shares"):
        print(f"\n✓ ASST common shares (basic/total): {dil['basic_shares']:,}")
        extracted["asst_shares_basic"] = dil["basic_shares"]
    if dil.get("effective_diluted_shares"):
        print(
            f"✓ ASST effective diluted (rNAV denom): "
            f"{dil['effective_diluted_shares']:,}"
        )
        extracted["asst_shares_diluted_effective"] = dil["effective_diluted_shares"]
        extracted["asst_shares"] = dil["rnav_denominator_shares"]
    if dil.get("gross_diluted_shares"):
        print(f"✓ ASST gross diluted (incl. OTM warrants): {dil['gross_diluted_shares']:,}")
        extracted["asst_shares_diluted_gross"] = dil["gross_diluted_shares"]
    if dil.get("breakdown"):
        extracted["asst_dilution_breakdown"] = dil["breakdown"]
        for b in dil["breakdown"]:
            tag = "eff" if b.get("include_in_effective_dilution") else "excl"
            print(f"    [{tag}] {b.get('name')}: {b.get('share_count'):,}")
    if dil.get("excluded_from_effective"):
        extracted["asst_dilution_excluded"] = dil["excluded_from_effective"]
    extracted["asst_dilution_policy"] = dil.get("policy")
    extracted["asst_dilution_source"] = dil.get("source")
    
    # Calculate cash from EV if we have all values
    if ev is not None and mcap is not None and notional:
        preferred_par_value = notional
        calculated_cash = mcap + preferred_par_value + debt - ev
        print(f"\n✓ Calculated Cash from EV Formula:")
        print(f"  Formula: cash = mcap + preferred_par + debt - EV")
        print(f"  Calculation: ${mcap:,.0f} + ${preferred_par_value:,.0f} + ${debt:,.0f} - ${ev:,.0f}")
        print(f"  Calculated Cash: ${calculated_cash:,.0f}")
        extracted['calculated_cash_from_ev'] = float(calculated_cash)
        
        if cash:
            diff = abs(calculated_cash - cash)
            print(f"  API Cash: ${cash:,.0f}")
            print(f"  Difference: ${diff:,.0f}")
            extracted['cash_difference'] = float(diff)
    
    # Add timestamp
    extracted['timestamp'] = datetime.now().isoformat()
    extracted['source'] = 'https://data.strategytracker.com/'
    
    # Save to file
    print(f"\n" + "="*70)
    print("SAVING DATA")
    print("="*70)
    out = output_path if output_path is not None else OUTPUT_DIR / "treasury_extracted_data.json"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, 'w') as f:
        json.dump(extracted, f, indent=2)
    print(f"✓ Saved to {out}")
    
    print(f"\n" + "="*70)
    print("COMPLETE DATA")
    print("="*70)
    print(json.dumps(extracted, indent=2))
    
    return extracted


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Fetch ASST/SATA data from strategytracker API")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Output JSON path (default: {OUTPUT_DIR / 'treasury_extracted_data.json'})",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass cache and refetch all network data",
    )
    args = parser.parse_args()
    ensure_output_dirs()
    out_path = args.output if args.output is not None else OUTPUT_DIR / "treasury_extracted_data.json"
    try:
        data = fetch_asst_data(output_path=out_path, force_refresh=args.force_refresh)
        if data:
            print("\n✓ Data extraction complete!")
        else:
            print("\n✗ Failed to extract data")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

