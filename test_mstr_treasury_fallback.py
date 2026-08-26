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


def test_apply_fallback_keeps_cms_strc_over_tracker_round(tmp_path: Path):
    seed = {
        "bitcoin_holdings": 840447,
        "strc_shares": 99_721_680,
        "strc_notional": 9_972_168_000.0,
        "cash": 1,
    }
    fb_path = tmp_path / "mstr_treasury_fallback.json"
    save_mstr_treasury_fallback(seed, path=fb_path)
    live = apply_mstr_treasury_fallback(
        {
            "bitcoin_holdings": 840447,
            "strc_shares": 101_153_000,
            "strc_notional": 10_115_300_000.0,
            "cash": 5_100_000_000,
        },
        path=fb_path,
    )
    assert live["strc_shares"] == 99_721_680
    assert live["strc_notional"] == 9_972_168_000.0
    assert live["cash"] == 5_100_000_000


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


def test_prefer_precise_share_counts_keeps_cms():
    from fetch_mstr_treasury import _prefer_precise_share_counts

    live = {
        "strc_shares": 101_153_000,
        "strd_shares": 14_024_200,
        "mstr_shares": 394_203_000,
    }
    fb = {
        "strc_shares": 99_721_680,
        "strd_shares": 14_024_221,
        "mstr_shares": 415_929_000,
    }
    _prefer_precise_share_counts(live, fb)
    assert live["strc_shares"] == 99_721_680
    assert live["strd_shares"] == 14_024_221
    assert live["mstr_shares"] == 415_929_000


def test_tracker_pref_shares_drops_common_pollution():
    from fetch_mstr_treasury import tracker_pref_shares

    common = 330_808_000
    strc = {
        "sharesOutstanding": common,
        "notionalUSD": 10_115_300_000.0,
    }
    assert tracker_pref_shares(strc, common) == 101_153_000
    strk = {"sharesOutstanding": 14_020_744, "notionalUSD": 1_402_070_000.0}
    assert tracker_pref_shares(strk, common) == 14_020_744


def test_mstr_raw_from_strategytracker_uses_notional_for_strc():
    from fetch_mstr_treasury import mstr_raw_from_strategytracker, mstr_treasury_is_usable

    company = {
        "processedMetrics": {
            "latestBtcBalance": 840447,
            "latestCashBalance": 5_100_000_000,
            "latestTotalShares": 394_203_000,
            "sharesOutstanding": 330_808_000,
            "latestDebt": 0,
            "preferredStocks": [
                {
                    "ticker": "STRC",
                    "sharesOutstanding": 330_808_000,
                    "notionalUSD": 10_115_300_000.0,
                    "dividendRate": 12.0,
                    "price": 97.3,
                },
                {
                    "ticker": "STRE",
                    "sharesOutstanding": 34_923_698,
                    "notionalUSD": 899_000_000.0,
                    "dividendRate": 10.0,
                    "price": 10.23,
                },
            ],
        }
    }
    raw = mstr_raw_from_strategytracker(company)
    assert mstr_treasury_is_usable(raw)
    assert raw["bitcoin_holdings"] == 840447
    assert raw["strc_shares"] == 101_153_000
    assert "stre_shares" not in raw  # misquoted LuxSE mark skipped
    assert "total_convertible_debt_principal" not in raw  # 0 debt ignored


def test_export_hydrates_empty_output_from_fallback(tmp_path: Path):
    from export_site_data import _load_mstr_site_inputs

    enriched, hedge, used = _load_mstr_site_inputs(tmp_path)
    assert used is True
    assert hedge.get("btc_holdings")
    assert enriched.get("bitcoin_holdings") or enriched.get("btc_holdings")
