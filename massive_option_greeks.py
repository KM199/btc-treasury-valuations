#!/usr/bin/env python3
"""
Fetch options greeks (delta, gamma, theta, vega) from Massive REST API.

Docs: https://massive.com/docs/rest/options/snapshots/option-chain-snapshot.md
Uses MASSIVE_API_KEY from .env (see python-dotenv).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Iterator

import requests
from dotenv import load_dotenv

MASSIVE_REST_BASE = os.environ.get("MASSIVE_REST_BASE", "https://api.massive.com")


def _require_api_key() -> str:
    load_dotenv()
    key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not key:
        print(
            "Missing MASSIVE_API_KEY. Add it to .env in the project root.",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def iter_option_chain_snapshots(
    underlying: str,
    api_key: str,
    *,
    expiration_date: str | None = None,
    contract_type: str | None = None,
    strike_price: float | None = None,
    limit: int = 250,
) -> Iterator[dict[str, Any]]:
    """
    Yield each contract snapshot dict from GET /v3/snapshot/options/{underlying},
    following next_url until exhausted.
    """
    params: dict[str, Any] = {"apiKey": api_key, "limit": min(limit, 250)}
    if expiration_date:
        params["expiration_date"] = expiration_date
    if contract_type:
        params["contract_type"] = contract_type.lower()
    if strike_price is not None:
        params["strike_price"] = strike_price

    url = f"{MASSIVE_REST_BASE.rstrip('/')}/v3/snapshot/options/{underlying.upper()}"
    first = True
    while url:
        r = requests.get(url, params=params if first else None, timeout=60)
        try:
            data = r.json()
        except ValueError:
            r.raise_for_status()
            raise
        if r.status_code != 200:
            msg = data.get("message") or data.get("error") or r.text
            raise RuntimeError(f"HTTP {r.status_code}: {msg}")
        if data.get("status") not in (None, "OK"):
            raise RuntimeError(f"API status: {data.get('status')!r}: {data}")
        for row in data.get("results") or []:
            yield row
        first = False
        params = None
        url = data.get("next_url") or ""


def snapshots_to_rows(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for s in snapshots:
        details = s.get("details") or {}
        greeks = s.get("greeks") or {}
        rows.append(
            {
                "ticker": details.get("ticker"),
                "contract_type": details.get("contract_type"),
                "expiration_date": details.get("expiration_date"),
                "strike_price": details.get("strike_price"),
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
                "implied_volatility": s.get("implied_volatility"),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Massive options chain greeks")
    parser.add_argument("underlying", nargs="?", default="IBIT", help="Underlying ticker, e.g. IBIT")
    parser.add_argument(
        "--expiration",
        "-e",
        help="Filter YYYY-MM-DD (optional)",
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=("call", "put"),
        help="call or put (optional)",
    )
    parser.add_argument(
        "--strike",
        "-k",
        type=float,
        help="Exact strike filter (optional)",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=500,
        help="Max contracts to collect (default 500)",
    )
    args = parser.parse_args()
    api_key = _require_api_key()

    out: list[dict[str, Any]] = []
    for row in iter_option_chain_snapshots(
        args.underlying,
        api_key,
        expiration_date=args.expiration,
        contract_type=args.type,
        strike_price=args.strike,
    ):
        out.append(row)
        if len(out) >= args.max:
            break

    if not out:
        print("No results (check plan access for options snapshots / filters).")
        return

    import pandas as pd

    df = pd.DataFrame(snapshots_to_rows(out))
    with pd.option_context("display.max_rows", 30, "display.width", 120):
        print(df.to_string(index=False))


if __name__ == "__main__":
    main()
