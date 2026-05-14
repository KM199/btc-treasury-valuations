#!/usr/bin/env python3
"""
Fetch data from treasury.strive.com using the actual API endpoints found in the JavaScript
"""

import requests
import json
from datetime import datetime

def fetch_treasury_data():
    """Fetch data using the actual API endpoints"""
    
    print("="*70)
    print("FETCHING TREASURY DATA FROM API")
    print("="*70)
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Referer': 'https://treasury.strive.com/',
        'Origin': 'https://treasury.strive.com'
    })
    
    # Step 1: Get latest version
    print("\n1. Fetching latest version...")
    latest_url = 'https://data.strategytracker.com/latest.json'
    try:
        response = session.get(latest_url, timeout=10)
        if response.status_code == 200:
            latest_data = response.json()
            version = latest_data.get('version')
            print(f"   ✓ Version: {version}")
            print(f"   Previous versions: {latest_data.get('previous_versions', [])}")
        else:
            print(f"   ✗ Failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return None
    
    # Step 2: Fetch ASST data using the version
    print(f"\n2. Fetching ASST data (version: {version})...")
    # Ticker is ASST (from the URL/companies data)
    ticker = 'ASST'
    # Replace dots with underscores as shown in the JS
    ticker_clean = ticker.replace('.', '_')
    
    asst_url = f'https://data.strategytracker.com/{ticker}.v{version}.json'
    print(f"   URL: {asst_url}")
    
    try:
        response = session.get(asst_url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            print(f"   ✓ Successfully fetched data")
            
            # Extract ASST company data
            companies = data.get('companies', {})
            asst = companies.get('ASST', {})
            
            if not asst:
                print(f"   ✗ ASST not found in companies. Available: {list(companies.keys())[:10]}")
                return None
            
            return extract_and_display_data(asst, data)
        else:
            print(f"   ✗ Failed: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def extract_and_display_data(asst, full_data):
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
    
    if debt:
        print(f"✓ Debt: ${debt:,.0f}")
        extracted['debt'] = float(debt)
    
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
    with open('treasury_extracted_data.json', 'w') as f:
        json.dump(extracted, f, indent=2)
    print(f"✓ Saved to treasury_extracted_data.json")
    
    print(f"\n" + "="*70)
    print("COMPLETE DATA")
    print("="*70)
    print(json.dumps(extracted, indent=2))
    
    return extracted


if __name__ == '__main__':
    try:
        data = fetch_treasury_data()
        if data:
            print("\n✓ Data extraction complete!")
        else:
            print("\n✗ Failed to extract data")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

