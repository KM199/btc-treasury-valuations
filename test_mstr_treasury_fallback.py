"""Committed MSTR treasury fallback — keeps the site buildable when strategy.com 403s."""

from __future__ import annotations

import json
from pathlib import Path

from fetch_mstr_treasury import (
    apply_mstr_treasury_fallback,
    load_mstr_treasury_fallback,
    mstr_treasury_is_usable,
    save_mstr_treasury_fallback,
)
from strc_paths import MSTR_TREASURY_FALLBACK_PATH


def test_committed_fallback_is_usable():
    data = load_mstr_treasury_fallback()
    assert data is not None
    assert mstr_treasury_is_usable(data)
    assert data["bitcoin_holdings"] > 0
    assert data["strc_shares"] > 0
    assert MSTR_TREASURY_FALLBACK_PATH.is_file()


def test_empty_scrape_is_not_usable():
    assert not mstr_treasury_is_usable({})
    assert not mstr_treasury_is_usable({"bitcoin_holdings": 0, "strc_shares": 10})
    assert not mstr_treasury_is_usable({"bitcoin_holdings": 100, "strc_shares": 0})
    assert not mstr_treasury_is_usable(None)


def test_btc_holdings_alias_counts():
    assert mstr_treasury_is_usable({"btc_holdings": 1, "strc_shares": 1})


def test_apply_fallback_fills_empty_scrape(tmp_path: Path):
    seed = {
        "bitcoin_holdings": 840447,
        "strc_shares": 99_721_680,
        "cash": 5_100_000_000,
        "usd_reserve_usd": 5_100_000_000,
        "source": "https://www.strategy.com/",
    }
    fb_path = tmp_path / "mstr_treasury_fallback.json"
    save_mstr_treasury_fallback(seed, path=fb_path)
    live = apply_mstr_treasury_fallback({}, path=fb_path)
    assert live["_from_fallback"] is True
    assert live["bitcoin_holdings"] == 840447
    assert live["strc_shares"] == 99_721_680


def test_apply_fallback_does_not_clobber_live(tmp_path: Path):
    seed = {
        "bitcoin_holdings": 1,
        "strc_shares": 1,
        "cash": 1,
    }
    fb_path = tmp_path / "mstr_treasury_fallback.json"
    save_mstr_treasury_fallback(seed, path=fb_path)
    live = apply_mstr_treasury_fallback(
        {"bitcoin_holdings": 840447, "strc_shares": 99_721_680, "cash": 0},
        path=fb_path,
    )
    assert "_from_fallback" not in live
    assert live["bitcoin_holdings"] == 840447
    assert live["cash"] == 1  # missing live cash filled from fallback


def test_save_skips_unusable(tmp_path: Path):
    path = tmp_path / "mstr_treasury_fallback.json"
    save_mstr_treasury_fallback({"bitcoin_holdings": 0, "strc_shares": 0}, path=path)
    assert not path.exists()


def test_export_hydrates_empty_output_from_fallback(tmp_path: Path):
    from export_site_data import _load_mstr_site_inputs

    enriched, hedge, used = _load_mstr_site_inputs(tmp_path)
    assert used is True
    assert hedge.get("btc_holdings")
    assert enriched.get("bitcoin_holdings") or enriched.get("btc_holdings")
