"""Cached Yahoo Finance spot/history helpers shared by fetch scripts."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from data_cache import get_or_fetch
from strc_paths import OUTPUT_DIR

DEFAULT_BTC_FALLBACK = 92000.0


def load_json_price(path: Path, key: str = "current_price") -> float | None:
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            raw = json.load(f)
        val = raw.get(key)
        if val is not None:
            return float(val)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def cached_yahoo_history(
    symbol: str,
    period: str = "1d",
    *,
    force_refresh: bool = False,
) -> pd.DataFrame | None:
    key = f"yahoo_history_{symbol}_{period}"

    def fetch() -> dict | None:
        df = yf.Ticker(symbol).history(period=period)
        if df.empty:
            return None
        return {
            "index": [ts.isoformat() for ts in df.index],
            "columns": list(df.columns),
            "data": df.values.tolist(),
        }

    raw = get_or_fetch(key, fetch, force_refresh=force_refresh)
    if raw is None:
        return None
    return pd.DataFrame(raw["data"], index=pd.to_datetime(raw["index"]), columns=raw["columns"])


def yahoo_spot_price(
    symbol: str,
    *,
    period: str = "1d",
    force_refresh: bool = False,
) -> float | None:
    """Latest close for symbol (cached)."""
    try:
        hist = cached_yahoo_history(symbol, period, force_refresh=force_refresh)
        if hist is not None and len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def load_btc_spot(
    output_dir: Path = OUTPUT_DIR,
    *,
    force_refresh: bool = False,
    fallback: float = DEFAULT_BTC_FALLBACK,
    log: bool = True,
) -> float:
    """Yahoo BTC-USD first (live when force_refresh); else btc_historical_data.json.

    Prefer live/cached Yahoo over historical JSON so path generation and the site
    do not silently reuse a weeks-old ``current_price`` snapshot.
    """
    price = yahoo_spot_price("BTC-USD", force_refresh=force_refresh)
    if price is not None:
        if log:
            src = "Yahoo (fresh)" if force_refresh else "Yahoo"
            print(f"  ✓ Current Bitcoin price ({src}): ${price:,.2f}")
        return price
    cached = load_json_price(output_dir / "btc_historical_data.json")
    if cached is not None:
        if log:
            print(
                f"  ✓ Bitcoin price from {output_dir / 'btc_historical_data.json'}: "
                f"${cached:,.2f}"
            )
        return cached
    if log:
        print(f"  ⚠ Using fallback Bitcoin price: ${fallback:,.2f}")
    return fallback
