#!/usr/bin/env python3
"""Fetch common-share dilution (warrants / options / RSUs) for ASST + MSTR.

Policy for rNAV denominators (avoid double-counting claims):
  • Preferreds (SATA, STRC, …) and convertible notes are **claims** in the
    rNAV numerator — never add their conversion shares to the denominator.
  • Dilution here is **common equity overhang only**: employee options, RSUs,
    and (when in-the-money / effective) warrants.

Sources
  ASST  data.strategytracker.com  → latestTotalShares, latestEffectiveDilutedShares,
        latestDilutedShareTypes (excludes OTM warrants from effective)
  MSTR  strategy.com/shares       → basic + options + RSU/PSU (already in
        fetch_mstr_treasury; converts recorded separately, excluded here)

Writes
  output/share_dilution.json
  patches asst_shares* into output/treasury_extracted_data.json when present
  patches mstr_shares* into output/mstr_enriched_data.json / mstr_treasury when present

Usage:
  python fetch_share_dilution.py
  python fetch_share_dilution.py --force-refresh
  python fetch_share_dilution.py --asst-only
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from data_cache import get_or_fetch
from strc_paths import OUTPUT_DIR, ensure_output_dirs

_TRACKER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) "
        "Gecko/20100101 Firefox/120.0"
    ),
    "Accept": "application/json",
    "Referer": "https://treasury.strive.com/",
    "Origin": "https://treasury.strive.com",
}

_STRATEGY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# PIPE Traditional Warrants (post 1-for-20): $1.35 → $27.00 strike.
# Expire on first anniversary of resale S-3ASR effectiveness (filed/effective 2025-09-15).
ASST_PIPE_WARRANT_EXPIRY = "2026-09-15"
ASST_PIPE_WARRANT_NOTE = (
    f"Expire {ASST_PIPE_WARRANT_EXPIRY}; deep OTM vs spot — likely expire worthless"
)

# Names that indicate a claim already counted in rNAV — never dilute for these
_CLAIM_NAME_RE = re.compile(
    r"convert|preferred|sata|strc|strd|strk|strf|stre|note\b|debenture",
    re.IGNORECASE,
)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def _fetch_json(url: str, headers: dict[str, str], timeout: float = 15) -> Any:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _fetch_text(url: str, headers: dict[str, str], timeout: float = 30) -> str:
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


def extract_asst_dilution(
    processed: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """Normalize strategytracker processedMetrics into a dilution record."""
    basic = int(
        processed.get("latestTotalShares")
        or processed.get("sharesOutstanding")
        or 0
    )
    effective = int(processed.get("latestEffectiveDilutedShares") or 0)
    gross = int(processed.get("latestDilutedShares") or 0)

    raw_types = processed.get("latestDilutedShareTypes") or []
    breakdown: list[dict[str, Any]] = []
    effective_add = 0
    excluded: list[dict[str, Any]] = []

    for row in raw_types:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        count = int(row.get("share_count") or 0)
        include = bool(row.get("include_in_effective_dilution"))
        entry = {
            "name": name,
            "share_count": count,
            "include_in_effective_dilution": include,
            "notes": row.get("notes") or "",
        }
        if re.search(r"warrant", name, re.I):
            entry["expiry"] = ASST_PIPE_WARRANT_EXPIRY
            entry["notes"] = entry["notes"] or ASST_PIPE_WARRANT_NOTE
        # Defensive: never treat preferred/convert labels as common dilution
        if _CLAIM_NAME_RE.search(name):
            entry["include_in_effective_dilution"] = False
            entry["excluded_reason"] = "claim_already_in_rnav"
            excluded.append(entry)
            continue
        breakdown.append(entry)
        if include:
            effective_add += count
        else:
            excluded.append(entry)

    if effective <= 0 and basic > 0:
        effective = basic + effective_add
    if gross <= 0:
        gross = basic + sum(b["share_count"] for b in breakdown) + sum(
            e["share_count"] for e in excluded if e.get("name")
        )

    # rNAV denominator: effective diluted common (ITM-aware overhang only)
    rnav_shares = effective if effective > 0 else basic

    return {
        "ticker": "ASST",
        "basic_shares": basic,
        "effective_diluted_shares": effective,
        "gross_diluted_shares": gross,
        "rnav_denominator_shares": rnav_shares,
        "overhang_effective": max(0, effective - basic) if basic and effective else effective_add,
        "breakdown": breakdown,
        "excluded_from_effective": excluded,
        "policy": (
            "rNAV uses effective diluted common (basic + RSUs/options and any "
            "ITM warrants). OTM warrants stay in gross only. SATA is a preferred "
            "claim in the numerator — not diluted here."
        ),
        "source": source,
    }


def fetch_asst_share_dilution(*, force_refresh: bool = False) -> dict[str, Any] | None:
    print("\n— ASST common share dilution (strategytracker) —")
    try:
        latest = get_or_fetch(
            "strategytracker_latest",
            lambda: _fetch_json(
                "https://data.strategytracker.com/latest.json", _TRACKER_HEADERS, 10
            ),
            force_refresh=force_refresh,
        )
        version = latest.get("version")
        if not version:
            print("  ✗ No version in latest.json")
            return None
        url = f"https://data.strategytracker.com/ASST.v{version}.json"
        data = get_or_fetch(
            f"strategytracker_ASST_v{version}",
            lambda: _fetch_json(url, _TRACKER_HEADERS, 15),
            force_refresh=force_refresh,
        )
        processed = (
            (data.get("companies") or {}).get("ASST", {}).get("processedMetrics") or {}
        )
        if not processed:
            print("  ✗ Missing processedMetrics")
            return None
        rec = extract_asst_dilution(
            processed, source=f"https://data.strategytracker.com/ASST.v{version}.json"
        )
        print(f"  ✓ Basic (total) shares:     {rec['basic_shares']:,}")
        print(f"  ✓ Effective diluted:        {rec['effective_diluted_shares']:,}")
        print(f"  ✓ Gross diluted:            {rec['gross_diluted_shares']:,}")
        print(f"  → rNAV denominator:         {rec['rnav_denominator_shares']:,}")
        for b in rec["breakdown"]:
            flag = "eff" if b["include_in_effective_dilution"] else "otm"
            print(f"      [{flag}] {b['name']}: {b['share_count']:,}")
        return rec
    except Exception as e:
        print(f"  ✗ ASST dilution fetch failed: {e}")
        return None


def extract_mstr_dilution_from_shares_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """strategy.com shares table is in thousands."""
    basic_k = float(entry.get("basic_shares_outstanding") or 0)
    options_k = float(entry.get("options_outstanding") or 0)
    rsu_k = float(entry.get("rsu_psu_unvested") or 0)
    assumed_k = float(entry.get("assumed_diluted_shares_outstanding") or 0)

    basic = int(basic_k * 1000)
    options = int(options_k * 1000)
    rsu = int(rsu_k * 1000)
    # rNAV denom: basic + equity awards only (excludes convert + preferred convert)
    rnav = basic + options + rsu
    assumed = int(assumed_k * 1000) if assumed_k else 0

    convert_keys = [
        k for k in entry if k.startswith("converts_shares_") or k == "strk"
    ]
    convert_shares = 0
    convert_breakdown = []
    for k in convert_keys:
        val = entry.get(k)
        if val is None:
            continue
        shares = int(float(val) * 1000)
        convert_shares += shares
        convert_breakdown.append({"name": k, "share_count": shares})

    return {
        "ticker": "MSTR",
        "as_of_date": entry.get("date"),
        "title": entry.get("title"),
        "basic_shares": basic,
        "options_outstanding": options,
        "rsu_psu_unvested": rsu,
        "rnav_denominator_shares": rnav,
        "assumed_diluted_shares_incl_converts": assumed,
        "convert_preferred_shares_excluded": convert_shares,
        "convert_breakdown": convert_breakdown,
        "breakdown": [
            {
                "name": "Options outstanding",
                "share_count": options,
                "include_in_effective_dilution": True,
            },
            {
                "name": "RSU/PSU unvested",
                "share_count": rsu,
                "include_in_effective_dilution": True,
            },
        ],
        "excluded_from_effective": (
            [
                {
                    "name": "Converts + STRK",
                    "share_count": convert_shares,
                    "include_in_effective_dilution": False,
                    "notes": (
                        "Strike / conversion too high — stay as debt "
                        "and preferred claims"
                    ),
                }
            ]
            if convert_shares > 0
            else []
        ),
        "policy": (
            "rNAV uses basic + employee options + RSU/PSU only. Convertible notes "
            "and STRK are NOT assumed to convert (uneconomic vs spot) — converts "
            "remain debt at market; STRK remains a preferred claim at market. "
            "Strategy's assumed-diluted headline that adds convert/STRK shares "
            "is ignored."
        ),
        "source": "https://www.strategy.com/shares",
    }


def fetch_mstr_share_dilution(*, force_refresh: bool = False) -> dict[str, Any] | None:
    print("\n— MSTR common share dilution (strategy.com/shares) —")
    # Prefer already-fetched enriched JSON when fresh enough; else scrape
    enriched = _load_json(OUTPUT_DIR / "mstr_enriched_data.json") or {}
    if (
        not force_refresh
        and enriched.get("mstr_shares_basic")
        and enriched.get("mstr_shares")
    ):
        convert_excluded = int(enriched.get("mstr_convert_shares_excluded") or 0)
        rec = {
            "ticker": "MSTR",
            "basic_shares": int(enriched["mstr_shares_basic"]),
            "options_outstanding": int(enriched.get("mstr_options_outstanding") or 0),
            "rsu_psu_unvested": int(enriched.get("mstr_rsu_psu_unvested") or 0),
            "rnav_denominator_shares": int(enriched["mstr_shares"]),
            "assumed_diluted_shares_incl_converts": int(
                enriched.get("mstr_shares_assumed_diluted") or 0
            ),
            "convert_preferred_shares_excluded": convert_excluded,
            "breakdown": [
                {
                    "name": "Options outstanding",
                    "share_count": int(enriched.get("mstr_options_outstanding") or 0),
                    "include_in_effective_dilution": True,
                },
                {
                    "name": "RSU/PSU unvested",
                    "share_count": int(enriched.get("mstr_rsu_psu_unvested") or 0),
                    "include_in_effective_dilution": True,
                },
            ],
            "excluded_from_effective": (
                [
                    {
                        "name": "Converts + STRK",
                        "share_count": convert_excluded,
                        "include_in_effective_dilution": False,
                        "notes": (
                            "Strike / conversion too high — stay as debt "
                            "and preferred claims"
                        ),
                    }
                ]
                if convert_excluded > 0
                else []
            ),
            "policy": (
                "rNAV uses basic + employee options + RSU/PSU only. Converts and "
                "STRK are not assumed to convert — debt / preferred claims in the "
                "numerator at market."
            ),
            "source": enriched.get("source") or "mstr_enriched_data.json",
        }
        print(f"  ✓ From cache/enriched: rNAV denom {rec['rnav_denominator_shares']:,}")
        return rec

    try:
        html = get_or_fetch(
            # Same cache key fetch_mstr_treasury.py uses for this identical URL, so
            # the two callers share one cached response instead of both hitting
            # strategy.com/shares live within the same fetch_data.py run.
            "strategy_com_shares",
            lambda: _fetch_text("https://www.strategy.com/shares", _STRATEGY_HEADERS),
            force_refresh=force_refresh,
        )
        # __NEXT_DATA__ blob
        m = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not m:
            print("  ✗ No __NEXT_DATA__ on strategy.com/shares")
            return _mstr_fallback_from_enriched(enriched)
        next_data = json.loads(m.group(1))
        shares_data = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("shares")
            or []
        )
        if not shares_data:
            print("  ✗ Empty shares[]")
            return _mstr_fallback_from_enriched(enriched)

        most_recent = None
        most_recent_date = None
        for entry in shares_data:
            date_str = entry.get("date") or ""
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if most_recent_date is None or d > most_recent_date:
                most_recent_date = d
                most_recent = entry

        if not most_recent:
            return _mstr_fallback_from_enriched(enriched)

        rec = extract_mstr_dilution_from_shares_entry(most_recent)
        print(f"  ✓ As of {rec.get('as_of_date')}: {rec.get('title')}")
        print(f"  ✓ Basic shares:             {rec['basic_shares']:,}")
        print(f"  ✓ Options:                  {rec['options_outstanding']:,}")
        print(f"  ✓ RSU/PSU:                  {rec['rsu_psu_unvested']:,}")
        print(f"  → rNAV denominator:         {rec['rnav_denominator_shares']:,}")
        print(
            f"  (Strategy assumed-diluted headline ignored: would add "
            f"{rec['convert_preferred_shares_excluded']:,} convert/STRK shares → "
            f"{rec['assumed_diluted_shares_incl_converts']:,}; "
            f"we keep converts as debt, STRK as preferred)"
        )
        return rec
    except Exception as e:
        print(f"  ✗ MSTR dilution fetch failed: {e}")
        return _mstr_fallback_from_enriched(enriched)


def _mstr_fallback_from_enriched(enriched: dict[str, Any]) -> dict[str, Any] | None:
    shares = int(enriched.get("mstr_shares") or 0)
    if shares <= 0:
        return None
    print(f"  ✓ Fallback mstr_shares from enriched: {shares:,}")
    return {
        "ticker": "MSTR",
        "basic_shares": int(enriched.get("mstr_shares_basic") or shares),
        "options_outstanding": int(enriched.get("mstr_options_outstanding") or 0),
        "rsu_psu_unvested": int(enriched.get("mstr_rsu_psu_unvested") or 0),
        "rnav_denominator_shares": shares,
        "policy": "Fallback from mstr_enriched_data.json",
        "source": "mstr_enriched_data.json",
    }


def patch_asst_treasury(asst: dict[str, Any], treasury_path: Path) -> None:
    data = _load_json(treasury_path) or {}
    data["asst_shares_basic"] = asst["basic_shares"]
    data["asst_shares_diluted_effective"] = asst["effective_diluted_shares"]
    data["asst_shares_diluted_gross"] = asst["gross_diluted_shares"]
    data["asst_shares"] = asst["rnav_denominator_shares"]  # primary for asst_nav
    data["asst_dilution_breakdown"] = asst.get("breakdown") or []
    data["asst_dilution_excluded"] = asst.get("excluded_from_effective") or []
    data["asst_dilution_policy"] = asst.get("policy")
    data["asst_dilution_source"] = asst.get("source")
    data["asst_dilution_updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_json(treasury_path, data)
    print(f"  ✓ Patched {treasury_path.name} (asst_shares={data['asst_shares']:,})")


def patch_mstr_jsons(mstr: dict[str, Any], output_dir: Path) -> None:
    fields = {
        "mstr_shares_basic": mstr.get("basic_shares"),
        "mstr_options_outstanding": mstr.get("options_outstanding"),
        "mstr_rsu_psu_unvested": mstr.get("rsu_psu_unvested"),
        "mstr_shares": mstr.get("rnav_denominator_shares"),
        "mstr_shares_assumed_diluted": mstr.get(
            "assumed_diluted_shares_incl_converts"
        ),
        "mstr_convert_shares_excluded": mstr.get(
            "convert_preferred_shares_excluded"
        ),
        "mstr_dilution_policy": mstr.get("policy"),
        "mstr_dilution_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    for name in (
        "mstr_enriched_data.json",
        "mstr_treasury_extracted_data.json",
        "mstr_strategy_raw.json",
    ):
        path = output_dir / name
        data = _load_json(path)
        if data is None:
            continue
        for k, v in fields.items():
            if v is not None:
                data[k] = v
        _save_json(path, data)
        print(f"  ✓ Patched {name} (mstr_shares={fields['mstr_shares']:,})")


def build_share_dilution(
    output_dir: Path = OUTPUT_DIR,
    *,
    force_refresh: bool = False,
    asst_only: bool = False,
    mstr_only: bool = False,
) -> dict[str, Any]:
    ensure_output_dirs()
    print("=" * 70)
    print("SHARE DILUTION (common overhang for rNAV)")
    print("=" * 70)

    out = output_dir / "share_dilution.json"
    # Preserve the other issuer when refreshing only one side
    prior = _load_json(out) or {}

    asst = None if mstr_only else fetch_asst_share_dilution(force_refresh=force_refresh)
    mstr = None if asst_only else fetch_mstr_share_dilution(force_refresh=force_refresh)

    payload: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "notes": {
            "rnav_rule": (
                "Denominator = common equity overhang only (options/RSUs/ITM warrants). "
                "Preferreds (incl. STRK) and convertible debt are subtracted as claims "
                "in the numerator. We do not assume converts or STRK convert."
            ),
            "yahoo": (
                "Do not use Yahoo impliedSharesOutstanding for dilution — it is "
                "mostly dual-class consolidation, not warrants/options/RSUs."
            ),
            "mstr_converts": (
                "MSTR convertible notes stay as debt MTM; STRK stays as preferred "
                "at market. Neither is assumed to convert into common. Strategy's "
                "assumed_diluted_shares_outstanding that adds those shares is ignored."
            ),
            "asst_warrants": (
                "ASST PIPE Traditional Warrants @ $27 (post-split) expire "
                f"{ASST_PIPE_WARRANT_EXPIRY} (1y after S-3ASR effective 2025-09-15). "
                "Deep OTM — excluded from rNAV denominator; likely expire worthless."
            ),
        },
    }

    if asst:
        payload["asst"] = asst
        patch_asst_treasury(asst, output_dir / "treasury_extracted_data.json")
    elif prior.get("asst"):
        payload["asst"] = prior["asst"]

    if mstr:
        payload["mstr"] = mstr
        patch_mstr_jsons(mstr, output_dir)
    elif prior.get("mstr"):
        payload["mstr"] = prior["mstr"]

    if "asst" not in payload or "mstr" not in payload:
        missing = [t for t in ("asst", "mstr") if t not in payload]
        raise RuntimeError(
            f"share_dilution.json incomplete — missing {missing}. "
            "Run without --asst-only/--mstr-only once, or check network fetch."
        )

    _save_json(out, payload)
    print(f"\n✓ Wrote {out}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch ASST/MSTR common-share dilution for rNAV denominators"
    )
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--asst-only", action="store_true")
    parser.add_argument("--mstr-only", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Default: {OUTPUT_DIR}",
    )
    args = parser.parse_args()
    build_share_dilution(
        args.output_dir,
        force_refresh=args.force_refresh,
        asst_only=args.asst_only,
        mstr_only=args.mstr_only,
    )


if __name__ == "__main__":
    main()
