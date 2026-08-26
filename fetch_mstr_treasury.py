#!/usr/bin/env python3
"""
Fetch MicroStrategy treasury data from strategy.com (homepage, /debt, /shares).

CI/Python is Akamai-blocked (HTTP 403); in that case holdings/cash/preferreds
come from data.strategytracker.com (same feed as ASST). Convertible debt is
omitted by the tracker (latestDebt is 0) and STRE is often misquoted — those
fields are filled from the committed mstr_treasury_fallback.json. Yahoo
enriches prices. Writes hedge JSON for mstr_options_hedge.ipynb.

Network responses are cached for 1 hour under output/cache/ (see data_cache.py).
Use --force-refresh to bypass the cache for a run.

Run after fetch_data.py (reuses btc_historical_data.json and mstr_data.json when present):
  python fetch_mstr_treasury.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import requests
import yfinance as yf
from bs4 import BeautifulSoup

from data_cache import cached_http_get
from mstr_liquidation import (
    total_preferred_annual_dividends_usd_from_tracker,
    usd_months_dividend_coverage_from_cash,
)
from strc_paths import MSTR_TREASURY_FALLBACK_PATH, OUTPUT_DIR, ensure_output_dirs
from fetch_yahoo import cached_yahoo_history, load_btc_spot, load_json_price, yahoo_spot_price

load_btc_price = load_btc_spot  # backward-compatible alias

# Stable treasury fields persisted to the committed fallback. Live Yahoo
# prices are re-fetched on every run; these are the scrape-only inputs.
_MSTR_FALLBACK_KEYS = (
    "bitcoin_holdings",
    "btc_holdings",
    "cash",
    "usd_reserve_usd",
    "annual_dividends",
    "annual_dividends_musd",
    "total_preferred_annual_dividends_usd",
    "mstr_shares",
    "strc_shares",
    "strd_shares",
    "stre_shares",
    "strk_shares",
    "strf_shares",
    "strc_notional",
    "strc_dividend_rate",
    "strc_effective_yield",
    "strd_notional",
    "stre_notional",
    "strk_notional",
    "strf_notional",
    "total_convertible_debt_principal",
    "total_convertible_debt_market_value",
    "convertible_debt",
    "stre_fx_rate",
    "stre_price_eur",
    "stre_price",
    "source",
    "as_of_date",
)


def mstr_treasury_is_usable(data: dict | None) -> bool:
    """True when a treasury dict has the holdings + STRC shares the site needs."""
    if not data:
        return False
    holdings = float(data.get("bitcoin_holdings") or data.get("btc_holdings") or 0)
    strc = float(data.get("strc_shares") or 0)
    return holdings > 0 and strc > 0


_SHARE_COUNT_KEYS = (
    "strc_shares",
    "strd_shares",
    "stre_shares",
    "strk_shares",
    "strf_shares",
    "mstr_shares",
)


def _prefer_precise_share_counts(live: dict, fb: dict) -> None:
    """Keep CMS share counts when the tracker only has million-rounded notionals."""
    for key in _SHARE_COUNT_KEYS:
        try:
            live_v = int(live.get(key) or 0)
            fb_v = int(fb.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if live_v <= 0 or fb_v <= 0 or live_v == fb_v:
            continue
        # Preferreds: tracker notionals are million-rounded (~1%). Common:
        # latestTotalShares vs CMS basic can differ more (~5%) without being
        # a real issuance; keep the last CMS count in that band.
        limit = 0.08 if key == "mstr_shares" else 0.03
        if abs(live_v - fb_v) / fb_v < limit:
            live[key] = fb_v
            notional_key = key.replace("_shares", "_notional")
            if fb.get(notional_key):
                live[notional_key] = fb[notional_key]


def load_mstr_treasury_fallback(path: Path | None = None) -> dict | None:
    """Load the committed last-known-good Strategy treasury, or None."""
    p = path if path is not None else MSTR_TREASURY_FALLBACK_PATH
    if not p.is_file():
        return None
    try:
        with p.open() as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and mstr_treasury_is_usable(data) else None


def save_mstr_treasury_fallback(data: dict, path: Path | None = None) -> None:
    """Persist scrape-only treasury fields so CI can survive a strategy.com 403."""
    if not mstr_treasury_is_usable(data):
        return
    p = path if path is not None else MSTR_TREASURY_FALLBACK_PATH
    payload: dict = {"_fallback_saved_at": datetime.now().isoformat()}
    for key in _MSTR_FALLBACK_KEYS:
        if key in data and data[key] not in (None, "", [], {}):
            payload[key] = data[key]
    holdings = payload.get("bitcoin_holdings") or payload.get("btc_holdings")
    if holdings:
        payload["bitcoin_holdings"] = int(holdings)
        payload["btc_holdings"] = int(holdings)
    payload["source"] = data.get("source") or "https://www.strategy.com/"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def apply_mstr_treasury_fallback(live: dict, path: Path | None = None) -> dict:
    """Fill a failed/partial strategy.com scrape from the committed fallback."""
    fb = load_mstr_treasury_fallback(path)
    dest = path if path is not None else MSTR_TREASURY_FALLBACK_PATH
    if mstr_treasury_is_usable(live):
        if fb:
            for key, value in fb.items():
                if str(key).startswith("_"):
                    continue
                if live.get(key) in (None, 0, 0.0, [], {}):
                    live[key] = value
            _prefer_precise_share_counts(live, fb)
        try:
            save_mstr_treasury_fallback(live, path=dest)
            print(f"  ✓ Updated fallback cache: {dest.name}")
        except OSError as exc:
            print(f"  ⚠ Could not update MSTR treasury fallback: {exc}")
        return live
    if not fb:
        print(
            "  ⚠ strategy.com treasury scrape returned no holdings "
            f"and {dest.name} is missing"
        )
        return live
    print(
        "  ⚠ strategy.com treasury scrape returned no holdings; "
        f"using committed fallback ({dest.name})"
    )
    out = dict(fb)
    for key, value in live.items():
        if value in (None, 0, 0.0, [], {}):
            continue
        out[key] = value
    out["_from_fallback"] = True
    return out


def convert_issue_market_value_usd(debt: dict) -> float:
    """Market value of one convert: prefer last_traded_price (% of par) × notional.

    strategy.com/debt shows Price and Market Val ($M). CMS ``market_value`` is
    sometimes stale/wrong, so we recompute from ``last_traded_price`` when present.
    Falls back to CMS market_value, then face/notional.
    """
    notional = float(debt.get("notional") or debt.get("principal") or 0)
    price = debt.get("last_traded_price")
    if price is not None and notional > 0:
        p = float(price)
        # Bond convention: 104.42 means 104.42% of face
        if 1.0 < p < 500.0:
            return notional * (p / 100.0)
    mv = debt.get("market_value")
    if mv is not None:
        return float(mv)
    return notional

STRATEGY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _find_btc_tracker_row(obj) -> dict | None:
    """Walk a Next.js payload for a row that still looks like btcTrackerData."""
    if isinstance(obj, dict):
        if obj.get("btc_holdings") is not None and (
            "strc_metrics" in obj or "cash" in obj
        ):
            return obj
        for value in obj.values():
            found = _find_btc_tracker_row(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_btc_tracker_row(value)
            if found is not None:
                return found
    return None


def _fetch_strategy_btc_tracker_latest(*, force_refresh: bool = False) -> dict | None:
    """Latest btcTrackerData row from strategy.com homepage (single cached HTTP GET)."""
    try:
        page_text = cached_http_get(
            "https://www.strategy.com/",
            headers=STRATEGY_HEADERS,
            timeout=15,
            cache_key="strategy_com_home",
            force=force_refresh,
        )
    except requests.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        print(f"  ✗ strategy.com homepage HTTP {status} (Akamai bot block, not a JSON rename)")
        return None
    except requests.RequestException as exc:
        print(f"  ✗ strategy.com homepage: {exc}")
        return None
    if not page_text:
        return None
    if "Access Denied" in page_text[:800]:
        print("  ✗ strategy.com homepage: Akamai Access Denied")
        return None
    soup = BeautifulSoup(page_text, "html.parser")
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script_tag or not script_tag.string:
        print("  ✗ strategy.com homepage: no __NEXT_DATA__ script")
        return None
    try:
        next_data = json.loads(script_tag.string)
    except (json.JSONDecodeError, TypeError, ValueError):
        print("  ✗ strategy.com homepage: __NEXT_DATA__ is not JSON")
        return None
    page_props = (next_data.get("props") or {}).get("pageProps") or {}
    btc_tracker_data = page_props.get("btcTrackerData")
    if isinstance(btc_tracker_data, list) and btc_tracker_data:
        row = btc_tracker_data[0]
        return row if isinstance(row, dict) else None
    found = _find_btc_tracker_row(page_props)
    if found is not None:
        print(
            "  ⚠ btcTrackerData key missing; recovered a holdings row from "
            f"pageProps keys {list(page_props)[:12]}"
        )
        return found
    print(
        "  ✗ strategy.com homepage: no btcTrackerData "
        f"(pageProps keys: {list(page_props)[:12]})"
    )
    return None


STRE_PAR_EUR = 100.0
# STRE IPO'd Nov 2025 at €80 (20% discount to par). Thin LuxSE liquidity; no Yahoo data.
STRE_MARKET_PRICE_EUR = 80.0


def stre_price_from_strategy_metrics(stre: dict) -> tuple[float, float] | None:
    """
    STRE USD/EUR from strategy.com stre_metrics (LuxSE — not on Yahoo).

    Uses explicit price/effective_yield when present; else stated amount outstanding
    (notional_intl × €100) / shares with strategy.com current_fx_rate.
    """
    stre = stre or {}
    fx = stre.get("current_fx_rate")
    if fx is None or float(fx) <= 0:
        return None
    fx = float(fx)

    if stre.get("price") is not None:
        price_eur = float(stre["price"])
        return price_eur, price_eur * fx

    div = stre.get("dividend")
    ey = stre.get("effective_yield")
    if div is not None and ey is not None and float(ey) > 0:
        d = float(div)
        e = float(ey)
        e = e / 100.0 if e > 1 else e
        price_eur = STRE_PAR_EUR * (d / 100.0) / e
        return price_eur, price_eur * fx

    shares = stre.get("shares")
    intl = stre.get("notional_intl")
    if shares and intl:
        # notional_intl: stated amount outstanding in €100 blocks (e.g. 7_750_000 → €775M).
        # Only use this when notional_intl matches the current share count (same offering tranche).
        # If more shares were issued since the original offering, this ratio gives a wrong price.
        discrepancy = abs(int(shares) - float(intl)) / max(float(intl), 1)
        if discrepancy < 0.05:
            notional_eur = float(intl) * STRE_PAR_EUR
            price_eur = notional_eur / int(shares)
            return price_eur, price_eur * fx

    return STRE_MARKET_PRICE_EUR, STRE_MARKET_PRICE_EUR * fx


def apply_stre_price_from_strategy(
    data: dict,
    *,
    force_refresh: bool = False,
) -> None:
    """Set stre_price / stre_price_eur on data from cached strategy.com btcTrackerData."""
    if data.get("stre_price"):
        return
    latest = _fetch_strategy_btc_tracker_latest(force_refresh=force_refresh)
    if not latest:
        return
    stre = latest.get("stre_metrics") or {}
    prices = stre_price_from_strategy_metrics(stre)
    if prices is None:
        return
    data["stre_price_eur"], data["stre_price"] = prices
    data["stre_fx_rate"] = float(stre.get("current_fx_rate") or 0)


def parse_strc_metrics_from_tracker(latest_data: dict) -> dict:
    """STRC fields from a btcTrackerData entry (no network)."""
    strc = latest_data.get("strc_metrics") or {}
    out: dict = {}
    if "shares" in strc:
        out["shares"] = int(strc["shares"])
    if strc.get("dividend") is not None:
        out["dividend_rate"] = float(strc["dividend"]) / 100.0
    if strc.get("notional") is not None:
        out["notional"] = float(strc["notional"])
    if strc.get("effective_yield") is not None:
        ey = float(strc["effective_yield"])
        out["effective_yield"] = ey / 100.0 if ey > 1 else ey
    if strc.get("price") is not None:
        out["price"] = float(strc["price"])
    if latest_data.get("as_of_date"):
        out["as_of_date"] = latest_data["as_of_date"]
    return out


def fetch_strc_metrics_from_strategy(*, force_refresh: bool = False) -> dict | None:
    """All STRC website metrics in one strategy.com request (cached)."""
    latest = _fetch_strategy_btc_tracker_latest(force_refresh=force_refresh)
    if latest is None:
        return None
    metrics = parse_strc_metrics_from_tracker(latest)
    return metrics or None


def tracker_pref_shares(pref: dict, common_shares: float | int | None) -> int:
    """Preferred share count from strategytracker, ignoring common-share pollution.

    The MSTR blob sometimes copies ``sharesOutstanding`` from the common stock
    onto STRC/STRD. ``notionalUSD / $100 par`` is the reliable claim size.
    """
    notional = pref.get("notionalUSD")
    from_notional = int(round(float(notional) / 100.0)) if notional else 0
    try:
        raw = int(pref.get("sharesOutstanding") or 0)
    except (TypeError, ValueError):
        raw = 0
    common = int(common_shares or 0)
    if common and raw and abs(raw - common) < max(1_000, int(common * 0.02)):
        return from_notional
    if raw and from_notional and raw > from_notional * 3:
        return from_notional
    return raw or from_notional


def mstr_raw_from_strategytracker(company: dict) -> dict:
    """Map a strategytracker MSTR company blob onto fetch_mstr_strategy_raw keys."""
    pm = company.get("processedMetrics") or {}
    data: dict = {"source": "https://data.strategytracker.com/"}
    holdings = pm.get("latestBtcBalance")
    if holdings:
        data["bitcoin_holdings"] = int(holdings)
        data["btc_holdings"] = int(holdings)
    cash = pm.get("latestCashBalance")
    if cash:
        data["cash"] = float(cash)
        data["usd_reserve_usd"] = float(cash)
    as_of = pm.get("latestTreasuryDate")
    if as_of:
        data["as_of_date"] = str(as_of)
    common = pm.get("latestTotalShares") or pm.get("sharesOutstanding")
    if common:
        data["mstr_shares"] = int(common)
    debt = pm.get("latestDebt")
    if debt:
        data["total_convertible_debt_principal"] = float(debt)

    common_f = float(common or 0)
    for pref in pm.get("preferredStocks") or []:
        ticker = str(pref.get("ticker") or "").strip().lower()
        if ticker not in {"strc", "strd", "stre", "strk", "strf"}:
            continue
        price = pref.get("price")
        if ticker == "stre" and price is not None and float(price) < 30:
            # LuxSE STRE is often mis-quoted here; leave shares/fx to fallback.
            continue
        shares = tracker_pref_shares(pref, common_f)
        if shares:
            data[f"{ticker}_shares"] = shares
            data[f"{ticker}_notional"] = float(pref.get("notionalUSD") or shares * 100.0)
        div = pref.get("dividendRate")
        if div is not None:
            d = float(div)
            data[f"{ticker}_dividend_rate"] = d / 100.0 if d > 1 else d
        ey = pref.get("effectiveYield")
        if ey is not None:
            e = float(ey)
            data[f"{ticker}_effective_yield"] = e / 100.0 if e > 1 else e
        if price is not None and float(price) > 0:
            data[f"{ticker}_price"] = float(price)
    return data


def fetch_mstr_from_strategytracker(*, force_refresh: bool = False) -> dict:
    """MSTR treasury from data.strategytracker.com (same API as ASST)."""
    print("  → data.strategytracker.com MSTR payload (Akamai-free)...")
    try:
        from fetch_asst_api import fetch_strategytracker_company

        company = fetch_strategytracker_company("MSTR", force_refresh=force_refresh)
    except Exception as exc:
        print(f"  ✗ strategytracker MSTR fetch failed: {exc}")
        return {}
    if not company:
        print("  ✗ strategytracker has no MSTR company blob")
        return {}
    data = mstr_raw_from_strategytracker(company)
    if mstr_treasury_is_usable(data):
        print(
            f"  ✓ strategytracker MSTR: {data['bitcoin_holdings']:,} BTC, "
            f"{int(data.get('strc_shares') or 0):,} STRC"
        )
    else:
        print("  ✗ strategytracker MSTR payload missing holdings/STRC shares")
    return data


def fetch_mstr_strategy_raw(*, force_refresh: bool = False) -> dict:
    """
    Fetch MicroStrategy financial data from strategy.com
    (homepage btcTrackerData + /debt + /shares).
    """
    print("Fetching MicroStrategy financial data from https://www.strategy.com/...")
    data: dict = {}

    try:
        latest_data = _fetch_strategy_btc_tracker_latest(force_refresh=force_refresh)
        if latest_data is None:
            print("  ✗ Could not load btcTrackerData from strategy.com")
        else:
            if "btc_holdings" in latest_data:
                data["bitcoin_holdings"] = int(latest_data["btc_holdings"])
                print(f"  ✓ Bitcoin holdings: {data['bitcoin_holdings']:,} BTC")

            if "cash" in latest_data:
                data["cash"] = float(latest_data["cash"])
                data["usd_reserve_usd"] = data["cash"]
                print(f"  ✓ Cash reserve: ${data['cash']:,.0f}")

            if "annual_dividends" in latest_data and latest_data["annual_dividends"] is not None:
                data["annual_dividends"] = float(latest_data["annual_dividends"])
                data["annual_dividends_musd"] = data["annual_dividends"]
                print(f"  ✓ Annual dividends (reported): ${data['annual_dividends']:,.1f}M")

            pref_annual = total_preferred_annual_dividends_usd_from_tracker(latest_data)
            if pref_annual > 0:
                data["total_preferred_annual_dividends_usd"] = pref_annual
                months = usd_months_dividend_coverage_from_cash(
                    float(latest_data.get("cash") or 0), pref_annual
                )
                print(
                    f"  ✓ Preferred annual dividends (stated coupons): ${pref_annual / 1e6:,.1f}M"
                )
                print(f"  ✓ USD months of dividend coverage: {months:.1f}")

            if "mstr_shares" in latest_data:
                data["mstr_shares"] = int(latest_data["mstr_shares"])
                print(f"  ✓ MSTR shares outstanding: {data['mstr_shares']:,}")
            elif "shares_outstanding" in latest_data:
                data["mstr_shares"] = int(latest_data["shares_outstanding"])
                print(f"  ✓ MSTR shares outstanding: {data['mstr_shares']:,}")

            strc_web = parse_strc_metrics_from_tracker(latest_data)
            if strc_web.get("shares") is not None:
                data["strc_shares"] = strc_web["shares"]
                print(f"  ✓ STRC shares: {data['strc_shares']:,}")
            if strc_web.get("dividend_rate") is not None:
                data["strc_dividend_rate"] = strc_web["dividend_rate"]
                print(f"  ✓ STRC dividend rate: {data['strc_dividend_rate']:.2%}")
            if strc_web.get("notional") is not None:
                data["strc_notional"] = strc_web["notional"]
            if strc_web.get("effective_yield") is not None:
                data["strc_effective_yield"] = strc_web["effective_yield"]
            if strc_web.get("price") is not None:
                data["strc_price"] = strc_web["price"]

            preferred_series = ["strc", "strd", "stre", "strk", "strf"]
            for series in preferred_series:
                metrics_key = f"{series}_metrics"
                if metrics_key in latest_data:
                    series_data = latest_data[metrics_key]
                    if "shares" in series_data:
                        shares = int(series_data["shares"])
                        data[f"{series}_shares"] = shares
                        if series != "strc":
                            print(f"  ✓ {series.upper()} shares: {shares:,}")
                        elif "strc_shares" not in data:
                            data["strc_shares"] = shares
                            print(f"  ✓ STRC shares: {shares:,}")

            if "stre_metrics" in latest_data:
                stre_px = stre_price_from_strategy_metrics(latest_data["stre_metrics"])
                if stre_px is not None:
                    data["stre_price_eur"], data["stre_price"] = stre_px
                    fx = latest_data["stre_metrics"].get("current_fx_rate")
                    if fx is not None:
                        data["stre_fx_rate"] = float(fx)
                    print(
                        f"  ✓ STRE price (strategy.com): €{data['stre_price_eur']:.2f} "
                        f"→ ${data['stre_price']:,.2f}"
                    )

            print(f"  ✓ Data date: {latest_data.get('as_of_date', 'N/A')}")

        print("\nFetching convertible debt data from https://www.strategy.com/debt...")
        try:
            debt_url = "https://www.strategy.com/debt"
            try:
                debt_text = cached_http_get(
                    debt_url,
                    headers=STRATEGY_HEADERS,
                    timeout=15,
                    cache_key="strategy_com_debt",
                    force=force_refresh,
                )
            except requests.RequestException as exc:
                print(f"  ✗ Could not fetch from strategy.com/debt: {exc}")
                debt_text = None

            if debt_text:
                debt_soup = BeautifulSoup(debt_text, "html.parser")
                debt_script_tag = debt_soup.find("script", {"id": "__NEXT_DATA__"})

                if debt_script_tag:
                    debt_next_data = json.loads(debt_script_tag.string)
                    debt_page_props = debt_next_data.get("props", {}).get("pageProps", {})
                    data["convertible_debt"] = []

                    if "convertData" in debt_page_props:
                        data["convertible_debt"] = debt_page_props["convertData"]
                        print(f"  ✓ Found convertible debt data: {len(data['convertible_debt'])} issues")
                    else:
                        for key in debt_page_props.keys():
                            if "debt" in key.lower() or "bond" in key.lower() or "convert" in key.lower():
                                debt_data = debt_page_props[key]
                                if isinstance(debt_data, list):
                                    data["convertible_debt"] = debt_data
                                    print(f"  ✓ Found convertible debt data: {len(debt_data)} issues")
                                    break

                        if not data["convertible_debt"]:
                            for key, value in debt_page_props.items():
                                if isinstance(value, list) and len(value) > 0:
                                    if isinstance(value[0], dict):
                                        first_item = value[0]
                                        if any(
                                            field in first_item
                                            for field in [
                                                "principal",
                                                "face_value",
                                                "amount",
                                                "notional",
                                                "strike_price",
                                                "strike",
                                            ]
                                        ):
                                            data["convertible_debt"] = value
                                            print(f"  ✓ Found convertible debt data: {len(value)} issues")
                                            break

                    if data["convertible_debt"]:
                        print(f"  ✓ Total convertible debt issues: {len(data['convertible_debt'])}")
                        for i, debt in enumerate(data["convertible_debt"], 1):
                            def get_value(d, *keys):
                                for key in keys:
                                    if key in d and d[key] is not None:
                                        val = d[key]
                                        if isinstance(val, str):
                                            try:
                                                val = val.replace("$", "").replace(",", "").strip()
                                                return float(val)
                                            except ValueError:
                                                return val
                                        return val
                                return None

                            def search_nested(d, target_keys):
                                if isinstance(d, dict):
                                    for key, value in d.items():
                                        if any(tk.lower() in key.lower() for tk in target_keys):
                                            if isinstance(value, (int, float)):
                                                return value
                                            if isinstance(value, str):
                                                try:
                                                    return float(
                                                        value.replace("$", "").replace(",", "").strip()
                                                    )
                                                except ValueError:
                                                    pass
                                        if isinstance(value, dict):
                                            result = search_nested(value, target_keys)
                                            if result is not None:
                                                return result
                                return None

                            principal = get_value(
                                debt,
                                "notional",
                                "principal",
                                "face_value",
                                "faceValue",
                                "amount",
                                "par_value",
                                "parValue",
                                "total_principal",
                                "totalPrincipal",
                            )
                            if principal is None:
                                principal = search_nested(
                                    debt, ["notional", "principal", "face", "amount", "par"]
                                )
                            principal = principal or 0

                            conversion_price = get_value(
                                debt,
                                "strike_price",
                                "strikePrice",
                                "strike",
                                "conversion_price",
                                "conversionPrice",
                                "conversion_strike",
                                "conversionStrike",
                                "conversion_rate",
                                "conversionRate",
                                "conversion",
                                "conversionPricePerShare",
                                "conversion_price_per_share",
                                "share_conversion_price",
                                "shareConversionPrice",
                                "price",
                            )
                            if conversion_price is None:
                                conversion_price = search_nested(debt, ["strike", "conversion", "price"])
                            conversion_price = conversion_price or 0

                            maturity = get_value(debt, "maturity_date", "maturityDate", "maturity") or "N/A"
                            coupon = get_value(
                                debt, "coupon", "coupon_rate", "couponRate", "interest_rate", "interestRate"
                            ) or 0

                            print(
                                f"    Issue {i}: Principal=${principal:,.0f}, "
                                f"Conversion Price=${conversion_price:,.2f}, "
                                f"Coupon={coupon}%, Maturity={maturity}"
                            )
                    else:
                        print("  ⚠ No convertible debt data found in debt page")
                else:
                    print("  ✗ Could not find __NEXT_DATA__ script tag in debt page")
            else:
                print("  ✗ Could not fetch from strategy.com/debt")
        except Exception as e:
            print(f"  ⚠ Error fetching debt data: {e}")
            import traceback

            traceback.print_exc()

        if data.get("convertible_debt"):
            total_debt_principal = 0.0
            total_debt_market = 0.0
            for debt in data["convertible_debt"]:
                notional = float(debt.get("notional") or 0)
                mtm = convert_issue_market_value_usd(debt)
                debt["market_value_usd"] = mtm
                if debt.get("last_traded_price") is not None:
                    debt["market_price_pct_par"] = float(debt["last_traded_price"])
                total_debt_principal += notional
                total_debt_market += mtm
            data["total_convertible_debt_principal"] = total_debt_principal
            data["total_convertible_debt_market_value"] = total_debt_market
            print(f"\n  ✓ Total convertible debt principal: ${total_debt_principal:,.0f}")
            print(f"  ✓ Total convertible debt market value: ${total_debt_market:,.0f}")
        # Do not write 0 debt on a failed /debt scrape — the committed
        # fallback (or a previous live parse) fills those keys later.

        print("\nFetching share conversion data from https://www.strategy.com/shares...")
        try:
            shares_url = "https://www.strategy.com/shares"
            try:
                shares_text = cached_http_get(
                    shares_url,
                    headers=STRATEGY_HEADERS,
                    timeout=15,
                    cache_key="strategy_com_shares",
                    force=force_refresh,
                )
            except requests.RequestException as exc:
                print(f"  ✗ Could not fetch from strategy.com/shares: {exc}")
                shares_text = None

            if shares_text:
                shares_soup = BeautifulSoup(shares_text, "html.parser")
                shares_script_tag = shares_soup.find("script", {"id": "__NEXT_DATA__"})

                if shares_script_tag:
                    shares_next_data = json.loads(shares_script_tag.string)
                    shares_page_props = shares_next_data.get("props", {}).get("pageProps", {})
                    shares_data = shares_page_props.get("shares", [])

                    if shares_data:
                        most_recent_entry = None
                        most_recent_date = None

                        for entry in shares_data:
                            date_str = entry.get("date", "")
                            if date_str:
                                try:
                                    entry_date = datetime.strptime(date_str, "%Y-%m-%d")
                                    if most_recent_date is None or entry_date > most_recent_date:
                                        most_recent_date = entry_date
                                        most_recent_entry = entry
                                except ValueError:
                                    pass

                        if most_recent_entry:
                            print(
                                f"  ✓ Using most recent shares data: "
                                f"{most_recent_entry.get('title', 'N/A')} "
                                f"({most_recent_entry.get('date', 'N/A')})"
                            )

                            basic_shares = most_recent_entry.get("basic_shares_outstanding", 0) or 0
                            options_outstanding = most_recent_entry.get("options_outstanding", 0) or 0
                            rsu_psu_unvested = most_recent_entry.get("rsu_psu_unvested", 0) or 0

                            if basic_shares > 0:
                                basic_shares_actual = int(basic_shares * 1000)
                                options_actual = int(options_outstanding * 1000) if options_outstanding > 0 else 0
                                rsu_psu_actual = int(rsu_psu_unvested * 1000) if rsu_psu_unvested > 0 else 0
                                # rNAV denominator: equity awards only — converts are claims
                                data["mstr_shares_basic"] = basic_shares_actual
                                data["mstr_options_outstanding"] = options_actual
                                data["mstr_rsu_psu_unvested"] = rsu_psu_actual
                                data["mstr_shares"] = (
                                    basic_shares_actual + options_actual + rsu_psu_actual
                                )
                                assumed_k = (
                                    most_recent_entry.get(
                                        "assumed_diluted_shares_outstanding"
                                    )
                                    or 0
                                )
                                if assumed_k:
                                    data["mstr_shares_assumed_diluted"] = int(
                                        float(assumed_k) * 1000
                                    )
                                data["mstr_dilution_policy"] = (
                                    "basic + options + RSU/PSU; converts and STRK "
                                    "NOT assumed to convert — debt / preferred claims"
                                )
                                print(f"  ✓ MSTR basic shares outstanding: {basic_shares_actual:,}")
                                if options_actual > 0:
                                    print(f"  ✓ Options outstanding: {options_actual:,}")
                                if rsu_psu_actual > 0:
                                    print(f"  ✓ RSU/PSU unvested: {rsu_psu_actual:,}")
                                print(f"  ✓ rNAV diluted shares (ex-converts): {data['mstr_shares']:,}")

                            conversion_shares = {
                                "2028": most_recent_entry.get("converts_shares_2028"),
                                "2029": most_recent_entry.get("converts_shares_2029"),
                                "2030": most_recent_entry.get("converts_shares_2030"),
                                "2030_b": most_recent_entry.get("converts_shares_2030_b"),
                                "2031": most_recent_entry.get("converts_shares_2031"),
                                "2032": most_recent_entry.get("converts_shares_2032"),
                            }
                        else:
                            conversion_shares = {}

                        if conversion_shares and data.get("convertible_debt"):
                            for debt in data["convertible_debt"]:
                                maturity_date = debt.get("maturity_date", "")
                                title = debt.get("title", "").lower()

                                if maturity_date:
                                    year = maturity_date.split("-")[0] if "-" in maturity_date else maturity_date[:4]

                                    if year == "2028":
                                        shares_val = conversion_shares.get("2028", 0) or 0
                                        debt["shares_on_conversion"] = shares_val * 1000 if shares_val > 0 else 0
                                    elif year == "2029":
                                        shares_val = conversion_shares.get("2029", 0) or 0
                                        debt["shares_on_conversion"] = shares_val * 1000 if shares_val > 0 else 0
                                    elif year == "2030":
                                        if "b" in title or "2030 b" in title:
                                            shares_val = conversion_shares.get("2030_b", 0) or 0
                                            debt["shares_on_conversion"] = shares_val * 1000 if shares_val > 0 else 0
                                        else:
                                            shares_val = conversion_shares.get("2030", 0) or 0
                                            debt["shares_on_conversion"] = shares_val * 1000 if shares_val > 0 else 0
                                    elif year == "2031":
                                        shares_val = conversion_shares.get("2031", 0) or 0
                                        debt["shares_on_conversion"] = shares_val * 1000 if shares_val > 0 else 0
                                    elif year == "2032":
                                        shares_val = conversion_shares.get("2032", 0) or 0
                                        debt["shares_on_conversion"] = shares_val * 1000 if shares_val > 0 else 0
                                    else:
                                        debt["shares_on_conversion"] = 0
                                else:
                                    debt["shares_on_conversion"] = 0
                    else:
                        print("  ⚠ No shares data found")
                else:
                    print("  ✗ Could not find __NEXT_DATA__ script tag in shares page")
            else:
                print("  ✗ Could not fetch from strategy.com/shares")
        except Exception as e:
            print(f"  ⚠ Error fetching shares data: {e}")
            import traceback

            traceback.print_exc()

    except Exception as e:
        print(f"  ✗ Error fetching from strategy.com: {e}")
        import traceback

        traceback.print_exc()

    return data


fetch_microstrategy_data = fetch_mstr_strategy_raw


def enrich_mstr_yahoo_prices(
    data: dict,
    output_dir: Path = OUTPUT_DIR,
    *,
    force_refresh: bool = False,
) -> dict:
    """
    Enrich data dict with Yahoo prices for MSTR and preferred tickers.
    Sets data['btc_price'] and returns the mutated dict.
    """
    print("\nFetching current prices...")
    btc_price = load_btc_spot(output_dir, force_refresh=force_refresh)

    # Prefer a live STRE mark; keep last-known prices if strategy.com 403s.
    prev_stre_usd = data.get("stre_price")
    prev_stre_eur = data.get("stre_price_eur")
    data.pop("stre_price", None)
    data.pop("stre_price_eur", None)
    apply_stre_price_from_strategy(data, force_refresh=force_refresh)
    if data.get("stre_price"):
        print(
            f"  ✓ STRE price from strategy.com: €{data.get('stre_price_eur', 0):.2f} "
            f"→ ${data['stre_price']:,.2f} (fx {data.get('stre_fx_rate', 0):.4f})"
        )
    elif prev_stre_usd:
        data["stre_price"] = prev_stre_usd
        if prev_stre_eur is not None:
            data["stre_price_eur"] = prev_stre_eur
        print(
            f"  ⚠ STRE price from last known treasury: "
            f"${float(prev_stre_usd):,.2f}"
        )

    mstr_cached = load_json_price(output_dir / "mstr_data.json")
    if mstr_cached is not None:
        data["mstr_price"] = mstr_cached
        print(f"  ✓ MSTR price from {output_dir / 'mstr_data.json'}: ${mstr_cached:,.2f}")
    else:
        print("\nFetching MSTR stock price from Yahoo Finance...")
        try:
            mstr_ticker = yf.Ticker("MSTR")
            mstr_info = mstr_ticker.info
            mstr_price_data = cached_yahoo_history("MSTR", "1d", force_refresh=force_refresh)
            if mstr_price_data is not None and len(mstr_price_data) > 0:
                data["mstr_price"] = float(mstr_price_data["Close"].iloc[-1])
                print(f"  ✓ MSTR price: ${data['mstr_price']:,.2f}")
            if "mstr_shares" not in data or data.get("mstr_shares", 0) == 0:
                if "sharesOutstanding" in mstr_info:
                    data["mstr_shares"] = int(mstr_info["sharesOutstanding"])
                    print(f"  ✓ MSTR shares outstanding (from Yahoo): {data['mstr_shares']:,}")
        except Exception as e:
            print(f"  ⚠ Error fetching MSTR data: {e}")

    strc_cached = load_json_price(output_dir / "strc_data.json")
    if strc_cached is not None:
        data["strc_price"] = strc_cached
        print(f"  ✓ STRC price from {output_dir / 'strc_data.json'}: ${strc_cached:,.2f}")

    preferred_series = ["strc", "strd", "strk", "strf"]
    for series in preferred_series:
        price_key = f"{series}_price"
        if price_key not in data or data.get(price_key, 0) == 0:
            print(f"\nFetching {series.upper()} price from Yahoo Finance...")
            try:
                price_data = cached_yahoo_history(series.upper(), "1d", force_refresh=force_refresh)
                if price_data is not None and len(price_data) > 0:
                    data[price_key] = float(price_data["Close"].iloc[-1])
                    print(f"  ✓ {series.upper()} price: ${data[price_key]:,.2f}")
                else:
                    print(f"  ⚠ Could not fetch {series.upper()} price from Yahoo Finance")
            except Exception as e:
                print(f"  ⚠ Error fetching {series.upper()} price: {e}")

    if not data.get("stre_price"):
        apply_stre_price_from_strategy(data, force_refresh=force_refresh)
        if data.get("stre_price"):
            print(
                f"  ✓ STRE price (strategy.com): €{data.get('stre_price_eur', 0):.2f} "
                f"→ ${data['stre_price']:,.2f}"
            )
        else:
            # LuxSE only, not on Yahoo. Use last persisted price from enriched file if available.
            eur_usd = data.get("stre_fx_rate") or 0.0
            if not eur_usd:
                eur_usd_price = yahoo_spot_price("EURUSD=X", force_refresh=force_refresh)
                eur_usd = eur_usd_price if eur_usd_price else 1.10
                data["stre_fx_rate"] = eur_usd

            prev_enriched_path = output_dir / "mstr_enriched_data.json"
            last_price_usd = None
            last_price_eur = None
            if prev_enriched_path.is_file():
                try:
                    prev = json.load(prev_enriched_path.open())
                    last_price_usd = prev.get("stre_price")
                    last_price_eur = prev.get("stre_price_eur")
                except Exception:
                    pass

            if last_price_eur and last_price_usd:
                data["stre_price_eur"] = last_price_eur
                data["stre_price"] = last_price_usd
                data["stre_price_stale"] = True
                print(
                    f"  ⚠ STRE price stale — no live source available. "
                    f"Using last known: €{last_price_eur:.2f} = ${last_price_usd:,.2f} "
                    f"(run fetch_mstr_treasury.py --force-refresh to update)"
                )
            else:
                data["stre_price_eur"] = STRE_MARKET_PRICE_EUR
                data["stre_price"] = STRE_MARKET_PRICE_EUR * eur_usd
                data["stre_price_stale"] = True
                print(
                    f"  ⚠ STRE price unavailable — using IPO market price "
                    f"€{STRE_MARKET_PRICE_EUR:.2f} × {eur_usd:.4f} = ${data['stre_price']:,.2f}"
                )

    data["btc_price"] = btc_price
    return data


def build_hedge_treasury_json(raw: dict, enriched: dict, btc_price: float) -> dict:
    """Normalize to slim hedge schema for mstr_options_hedge.ipynb."""
    cash = float(enriched.get("cash") or raw.get("cash") or 0)
    annual_div_musd = float(
        enriched.get("annual_dividends") if enriched.get("annual_dividends") is not None
        else raw.get("annual_dividends") or 0
    )
    pref_annual_usd = float(
        enriched.get("total_preferred_annual_dividends_usd")
        if enriched.get("total_preferred_annual_dividends_usd") is not None
        else raw.get("total_preferred_annual_dividends_usd") or 0
    )
    strc_shares = int(enriched.get("strc_shares") or raw.get("strc_shares") or 0)
    strc_price = float(enriched.get("strc_price") or 0)
    strc_notional = enriched.get("strc_notional") if enriched.get("strc_notional") is not None else raw.get("strc_notional")
    if strc_notional is None:
        strc_notional = float(strc_shares * 100)
    else:
        strc_notional = float(strc_notional)

    strc_div = enriched.get("strc_dividend_rate") if enriched.get("strc_dividend_rate") is not None else raw.get("strc_dividend_rate")
    strc_div_rate = float(strc_div or 0)
    strc_yield = enriched.get("strc_effective_yield") if enriched.get("strc_effective_yield") is not None else raw.get("strc_effective_yield")
    strc_effective_yield = float(strc_yield or 0)

    strf_shares = int(enriched.get("strf_shares") or raw.get("strf_shares") or 0)
    strf_price = float(enriched.get("strf_price") or 0)
    debt_principal = float(
        enriched.get("total_convertible_debt_principal")
        if enriched.get("total_convertible_debt_principal") is not None
        else raw.get("total_convertible_debt_principal") or 0
    )
    debt_market = float(
        enriched.get("total_convertible_debt_market_value")
        if enriched.get("total_convertible_debt_market_value") is not None
        else raw.get("total_convertible_debt_market_value")
        if raw.get("total_convertible_debt_market_value") is not None
        else debt_principal
    )

    return {
        "btc_holdings": int(enriched.get("bitcoin_holdings") or raw.get("bitcoin_holdings") or 0),
        "btc_price": float(btc_price),
        "usd_reserve_usd": cash,
        "annual_dividends_musd": annual_div_musd,
        "total_preferred_annual_dividends_usd": pref_annual_usd,
        "convertible_debt_principal": debt_principal,
        "convertible_debt_market_value": debt_market,
        "strc_shares": strc_shares,
        "strc_notional": strc_notional,
        "strc_price": strc_price,
        "strc_dividend_rate": strc_div_rate,
        "strc_effective_yield": strc_effective_yield,
        "strf_shares": strf_shares,
        "strf_price": strf_price,
        "strf_market_value": strf_shares * strf_price,
        "timestamp": datetime.now().isoformat(),
        "source": raw.get("source")
        or enriched.get("source")
        or "https://www.strategy.com/",
    }


def load_mstr_strategy_raw(
    output_dir: Path = OUTPUT_DIR,
    *,
    force_refresh: bool = False,
) -> dict:
    """Parse strategy.com data via the 1h HTTP cache; save result to disk."""
    data = fetch_mstr_strategy_raw(force_refresh=force_refresh)
    if not mstr_treasury_is_usable(data):
        tracker = fetch_mstr_from_strategytracker(force_refresh=force_refresh)
        if mstr_treasury_is_usable(tracker):
            merged = dict(data)
            merged.update(
                {k: v for k, v in tracker.items() if v not in (None, "", [], {})}
            )
            data = merged
    data = apply_mstr_treasury_fallback(data)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "mstr_strategy_raw.json"
    with raw_path.open("w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✓ Saved strategy.com raw data to {raw_path}")
    return data


def load_mstr_enriched(
    output_dir: Path = OUTPUT_DIR,
    *,
    max_age_hours: float = 24.0,
) -> dict:
    """Load fully enriched MSTR data from disk. Run fetch_mstr_treasury.py to refresh."""
    import os
    import time

    enriched_path = output_dir / "mstr_enriched_data.json"
    if not enriched_path.is_file():
        raise FileNotFoundError(
            f"Enriched data not found at {enriched_path}. "
            "Run: python fetch_mstr_treasury.py"
        )
    age_hours = (time.time() - os.path.getmtime(enriched_path)) / 3600
    if age_hours > max_age_hours:
        print(
            f"  ⚠ Enriched data is {age_hours:.1f}h old (>{max_age_hours:.0f}h). "
            "Run: python fetch_mstr_treasury.py"
        )
    with enriched_path.open() as f:
        data = json.load(f)
    fetched_at = data.get("_fetched_at", "unknown")[:19]
    print(f"  ✓ Loaded enriched MSTR data from {enriched_path} (fetched: {fetched_at})")
    return data


def fetch_and_save_mstr_treasury(
    output_path: Path | None = None,
    output_dir: Path | None = None,
    *,
    force_refresh: bool = False,
) -> dict:
    """Fetch strategy.com data, enrich prices, write hedge JSON and enriched data."""
    ensure_output_dirs()
    out_dir = output_dir if output_dir is not None else OUTPUT_DIR
    raw = load_mstr_strategy_raw(out_dir, force_refresh=force_refresh)
    enriched = enrich_mstr_yahoo_prices(raw, output_dir=out_dir, force_refresh=force_refresh)
    btc_price = float(enriched.get("btc_price") or load_btc_spot(out_dir, force_refresh=force_refresh, log=False))
    hedge = build_hedge_treasury_json(raw, enriched, btc_price)

    out_path = Path(output_path) if output_path is not None else out_dir / "mstr_treasury_extracted_data.json"
    with out_path.open("w") as f:
        json.dump(hedge, f, indent=2)
    print(f"\n✓ Saved hedge treasury data to {out_path}")

    # Save full enriched dict for MSTR.ipynb (all prices, shares, holdings, debt).
    enriched["_fetched_at"] = datetime.now().isoformat()
    enriched_path = out_dir / "mstr_enriched_data.json"
    with enriched_path.open("w") as f:
        json.dump(enriched, f, indent=2, default=str)
    print(f"✓ Saved enriched data to {enriched_path}")

    return hedge


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch MSTR treasury data from strategy.com")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"Output JSON path (default: {OUTPUT_DIR / 'mstr_treasury_extracted_data.json'})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory when --output is omitted (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--force-refresh",
        "--no-cache",
        action="store_true",
        dest="force_refresh",
        help="Bypass cache and refetch all network data",
    )
    args = parser.parse_args()
    fetch_and_save_mstr_treasury(
        output_path=args.output,
        output_dir=args.output_dir,
        force_refresh=args.force_refresh,
    )
