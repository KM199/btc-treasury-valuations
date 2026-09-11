"""
Regression: a dividend-paying ticker must never silently enrich its chain at q = 0.

``ibit_option_deltas`` prices on a CRR tree whose forward is S·e^{(r−q)T}, so q is a
yield on spot. It used to fall back to ``DEFAULT_DIV_YIELD = 0.0`` whenever the ticker
JSON had no ``dividend_yield`` — which is exactly what strategy.com's HTTP 403 produces
for STRC. Solving a ~12% payer's puts at q = 0 overstated implied vol by 4–9 points and
corrupted every Δ/Γ/ρ derived from it.

Builds its own JSON fixtures in a temp dir — runs anywhere, no fetched data required.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ibit_option_deltas import (
    DIVIDEND_PAYING_TICKERS,
    NON_DIVIDEND_TICKERS,
    PREFERRED_STATED_AMOUNT,
    MissingDividendYieldError,
    enrich_options_files,
    is_options_chain_enriched,
    resolve_dividend_yield,
    yield_on_spot_from_par_rate,
)

SPOT = 98.67
FAR_EXPIRY = "2027-03-19"


def _chain(spot: float = SPOT, **extra) -> dict:
    """Minimal ticker JSON with one liquid OTM put and one ITM call."""
    data = {
        "timestamp": "2026-09-11T12:33:45.506985",
        "current_price": spot,
        "options_data": {
            FAR_EXPIRY: {
                "calls": [{"strike": 95.0, "bid": 3.70, "ask": 4.00}],
                "puts": [{"strike": 90.0, "bid": 2.35, "ask": 3.30}],
            }
        },
    }
    data.update(extra)
    return data


def _write(tmp: Path, ticker: str, data: dict) -> Path:
    path = tmp / f"{ticker}_data.json"
    path.write_text(json.dumps(data))
    return path


def _treasury(tmp: Path, **fields) -> None:
    (tmp / "mstr_treasury_extracted_data.json").write_text(json.dumps(fields))


class TestDividendYieldResolution(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_payer_without_any_source_raises_instead_of_zero(self):
        """The headline bug: no yield anywhere must error, not quietly become q = 0."""
        with self.assertRaises(MissingDividendYieldError) as ctx:
            resolve_dividend_yield("strc", {}, SPOT, output_dir=self.tmp)
        self.assertIn("STRC", str(ctx.exception))

    def test_par_coupon_is_rescaled_onto_spot(self):
        """12% of $100 par at $98.67 spot is a 12.16% yield, not 12.00%."""
        _treasury(self.tmp, strc_dividend_rate=0.12)
        q, source = resolve_dividend_yield("strc", {}, SPOT, output_dir=self.tmp)
        self.assertAlmostEqual(q, 0.12 * PREFERRED_STATED_AMOUNT / SPOT, places=12)
        self.assertGreater(q, 0.12)
        self.assertIn("strc_dividend_rate", source)

    def test_effective_yield_used_when_par_coupon_absent(self):
        _treasury(self.tmp, strc_effective_yield=0.12177116154466716)
        q, source = resolve_dividend_yield("strc", {}, SPOT, output_dir=self.tmp)
        self.assertAlmostEqual(q, 0.12177116154466716, places=12)
        self.assertIn("strc_effective_yield", source)

    def test_percentage_style_rates_are_normalised(self):
        _treasury(self.tmp, strc_dividend_rate=12.0)
        q, _ = resolve_dividend_yield("strc", {}, SPOT, output_dir=self.tmp)
        self.assertAlmostEqual(q, 0.12 * PREFERRED_STATED_AMOUNT / SPOT, places=12)

    def test_stored_zero_on_a_payer_is_treated_as_missing(self):
        """Chains written by the buggy version carry dividend_yield 0.0 — re-derive."""
        _treasury(self.tmp, strc_dividend_rate=0.12)
        q, source = resolve_dividend_yield(
            "strc", {"dividend_yield": 0.0}, SPOT, output_dir=self.tmp
        )
        self.assertGreater(q, 0.1)
        self.assertIn("strc_dividend_rate", source)

    def test_non_payers_get_an_explicit_zero(self):
        for ticker in sorted(NON_DIVIDEND_TICKERS):
            q, source = resolve_dividend_yield(ticker, {}, 36.39, output_dir=self.tmp)
            self.assertEqual(q, 0.0)
            self.assertEqual(source, "none-expected")

    def test_non_strict_mode_warns_but_labels_the_result_untrusted(self):
        q, source = resolve_dividend_yield("strc", {}, SPOT, output_dir=self.tmp, strict=False)
        self.assertEqual(q, 0.0)
        self.assertEqual(source, "MISSING-assumed-zero")

    def test_override_wins(self):
        _treasury(self.tmp, strc_dividend_rate=0.12)
        q, source = resolve_dividend_yield("strc", {}, SPOT, output_dir=self.tmp, override=0.05)
        self.assertEqual(q, 0.05)
        self.assertIn("override", source)

    def test_par_rate_conversion_rejects_a_dead_spot(self):
        with self.assertRaises(ValueError):
            yield_on_spot_from_par_rate(0.12, 0.0)


class TestChainEnrichmentNeverSilentlyZero(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _enrich(self, ticker: str, **kwargs):
        path = _write(self.tmp, ticker, _chain())
        return path, enrich_options_files(
            path,
            self.tmp / f"{ticker}_options.json",
            flat_risk_free=0.0394,
            tree_steps=64,
            quiet=True,
            **kwargs,
        )

    def test_payer_chain_refuses_to_enrich_without_a_yield(self):
        path = _write(self.tmp, "strc", _chain())
        with self.assertRaises(MissingDividendYieldError):
            enrich_options_files(
                path, self.tmp / "strc_options.json", flat_risk_free=0.0394, tree_steps=64, quiet=True
            )
        # Nothing was written, so nothing downstream can mistake it for good data.
        self.assertIsNone(json.loads(path.read_text())["options_data"][FAR_EXPIRY]["puts"][0].get("delta"))

    def test_enriched_payer_chain_records_a_positive_trusted_yield(self):
        _treasury(self.tmp, strc_dividend_rate=0.12)
        path, (ok, _skipped, q, source) = self._enrich("strc")
        self.assertGreater(ok, 0)
        self.assertGreater(q, 0.1)
        stored = json.loads(path.read_text())
        self.assertAlmostEqual(stored["dividend_yield"], q, places=12)
        self.assertEqual(stored["dividend_yield_source"], source)
        self.assertIn("strc_dividend_rate", source)

    def test_ignoring_the_dividend_inflates_put_vol(self):
        """The measured failure mode: q = 0 pushes the solved put IV several points high."""
        _treasury(self.tmp, strc_dividend_rate=0.12)
        _, (_ok, _sk, q, _src) = self._enrich("strc")
        right = json.loads((self.tmp / "strc_data.json").read_text())

        _write(self.tmp, "strc", _chain())
        enrich_options_files(
            self.tmp / "strc_data.json",
            self.tmp / "strc_options.json",
            flat_risk_free=0.0394,
            div_yield=0.0,
            tree_steps=64,
            quiet=True,
        )
        wrong = json.loads((self.tmp / "strc_data.json").read_text())

        iv_right = right["options_data"][FAR_EXPIRY]["puts"][0]["implied_volatility"]
        iv_wrong = wrong["options_data"][FAR_EXPIRY]["puts"][0]["implied_volatility"]
        self.assertIsNotNone(iv_right)
        self.assertIsNotNone(iv_wrong)
        self.assertGreater(iv_wrong - iv_right, 0.03, "q=0 should overstate put IV by >3 vol points")

    def test_non_payer_chain_enriches_at_an_explicit_zero(self):
        _path, (ok, _skipped, q, source) = self._enrich("ibit")
        self.assertGreater(ok, 0)
        self.assertEqual(q, 0.0)
        self.assertEqual(source, "none-expected")

    def test_stale_zero_yield_chain_is_not_considered_enriched(self):
        """A payer's chain enriched at q=0 must be re-enriched, not skipped as fresh."""
        rows = _chain(dividend_yield=0.0)
        rows["options_data"][FAR_EXPIRY]["puts"][0].update(
            {"delta": -0.26, "gamma": 0.0017, "implied_volatility": 0.252}
        )
        path = _write(self.tmp, "strc", rows)
        self.assertFalse(is_options_chain_enriched(path))

        trusted = _chain(
            dividend_yield=0.1216,
            dividend_yield_source="mstr_treasury_extracted_data.json:strc_dividend_rate×par/spot",
        )
        trusted["options_data"][FAR_EXPIRY]["puts"][0].update(
            {"delta": -0.34, "gamma": 0.0017, "implied_volatility": 0.183}
        )
        self.assertTrue(is_options_chain_enriched(_write(self.tmp, "strc", trusted)))

    def test_every_payer_in_the_registry_is_distinct_from_the_non_payers(self):
        self.assertFalse(DIVIDEND_PAYING_TICKERS & NON_DIVIDEND_TICKERS)
        self.assertIn("strc", DIVIDEND_PAYING_TICKERS)


if __name__ == "__main__":
    unittest.main()
