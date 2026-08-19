"""Tests for the monthly dividend waterfall in ``sata_valuation``.

Covers the payment order (cash always, Bitcoin only above the gate), the
suspension gate itself, and the compounded-dividend arrears mechanics from the
SATA certificate of designation: an unpaid regular dividend accrues at the
regular dividend rate + 25bps, stepping up 25bps for each further month it
stays outstanding, capped at 20% per annum, compounded monthly until paid.

No fetched data required — every case builds its own config dict.
"""

import unittest

import numpy as np

from sata_valuation import Configuration, simulate_single_dividend_path


COUPON = 0.13
MONTHLY_DIVIDEND = 100.0


def make_config(**overrides):
    """Minimal config dict for simulate_single_dividend_path."""
    config = {
        "total_months": 6,
        "sata_monthly_dividend_total": MONTHLY_DIVIDEND,
        "total_par_value": 1000.0,
        "coverage_claim_value": 1000.0,
        "dividend_suspension_threshold_multiplier": 1.0,
        "compounded_dividend_start_rate": COUPON,
        "compounded_dividend_increment": 0.0025,
        "compounded_dividend_max_rate": 0.20,
        "monthly_discount_rate": 0.0,
    }
    config.update(overrides)
    return config


def expected_arrears(months_missed, start_rate=COUPON, increment=0.0025, cap=0.20):
    """Reference implementation of the certificate's compounding, month by month."""
    balance = 0.0
    for month in range(months_missed):
        if balance > 0 and month > 0:
            rate = min(start_rate + month * increment, cap)
            balance *= 1 + rate / 12
        balance += MONTHLY_DIVIDEND
    return balance


def run(cash, btc, prices, config=None, **kwargs):
    config = config or make_config()
    return simulate_single_dividend_path(
        cash, btc, np.asarray(prices, dtype=float), config,
        enable_early_termination=False, **kwargs
    )


class TestPaymentOrder(unittest.TestCase):
    def test_cash_pays_even_when_bitcoin_is_below_the_gate(self):
        """Cash is never gated — the reserve funds coupons at any Bitcoin price."""
        config = make_config(total_months=3)
        # 1 BTC at $1 against a $1,000 claim: the gate is shut all three months.
        months_paid, btc, cash, arrears, flows = run(300.0, 1.0, [1.0] * 3, config)

        self.assertEqual(months_paid, 3)
        self.assertEqual(arrears, 0.0)
        self.assertAlmostEqual(cash, 0.0)
        self.assertAlmostEqual(btc, 1.0, msg="no Bitcoin should be sold below the gate")
        self.assertAlmostEqual(flows.sum(), 300.0)

    def test_cash_runs_to_zero_before_any_bitcoin_is_sold(self):
        """With the gate open, cash is still spent first."""
        config = make_config(total_months=2)
        # 100 BTC at $100 = $10,000, comfortably above the $1,000 claim.
        months_paid, btc, cash, arrears, flows = run(150.0, 100.0, [100.0] * 2, config)

        self.assertEqual(months_paid, 2)
        self.assertAlmostEqual(cash, 0.0, msg="cash must be exhausted first")
        # $200 of coupons, $150 from cash, $50 from Bitcoin = 0.5 BTC at $100.
        self.assertAlmostEqual(btc, 99.5)
        self.assertAlmostEqual(flows.sum(), 200.0)

    def test_bitcoin_funds_the_shortfall_once_cash_is_gone(self):
        config = make_config(total_months=3)
        months_paid, btc, cash, arrears, flows = run(0.0, 100.0, [100.0] * 3, config)

        self.assertEqual(months_paid, 3)
        self.assertEqual(arrears, 0.0)
        self.assertAlmostEqual(btc, 97.0)


class TestSuspensionGate(unittest.TestCase):
    def test_gate_is_measured_against_coverage_claim_not_par(self):
        """coverage_claim_value drives the gate; total_par_value is ignored."""
        # Par is $1,000 but the net claim is $500. 6 BTC at $100 = $600:
        # above the net claim, below par. The gate must be open.
        config = make_config(total_months=1, total_par_value=1000.0,
                             coverage_claim_value=500.0)
        months_paid, btc, _cash, arrears, _flows = run(0.0, 6.0, [100.0], config)

        self.assertEqual(months_paid, 1, "netting the claim down should open the gate")
        self.assertEqual(arrears, 0.0)
        self.assertLess(btc, 6.0)

    def test_gate_shut_suspends_the_dividend_without_selling_bitcoin(self):
        config = make_config(total_months=1, coverage_claim_value=5000.0)
        months_paid, btc, _cash, arrears, flows = run(0.0, 6.0, [100.0], config)

        self.assertEqual(months_paid, 0)
        self.assertAlmostEqual(btc, 6.0, msg="no liquidation below the gate")
        self.assertAlmostEqual(flows.sum(), 0.0)
        self.assertAlmostEqual(arrears, MONTHLY_DIVIDEND,
                               msg="first missed month joins arrears at face")

    def test_threshold_multiplier_override_beats_the_config_value(self):
        config = make_config(total_months=1, coverage_claim_value=1000.0)
        # 6 BTC at $100 = $600 vs a $1,000 claim: shut at 1.0x, open at 0.5x.
        shut, *_ = run(0.0, 6.0, [100.0], config, threshold_multiplier=1.0)
        open_, *_ = run(0.0, 6.0, [100.0], config, threshold_multiplier=0.5)

        self.assertEqual(shut, 0)
        self.assertEqual(open_, 1)


class TestArrearsCompounding(unittest.TestCase):
    def test_outstanding_balance_compounds_not_just_the_new_shortfall(self):
        """The whole arrears balance compounds monthly, per the certificate."""
        config = make_config(total_months=6)
        _months_paid, _btc, _cash, arrears, _flows = run(0.0, 0.0, [1.0] * 6, config)

        self.assertAlmostEqual(arrears, expected_arrears(6), places=6)
        # Guard against the old behaviour, which only interest-loaded each new
        # shortfall and left the balance flat.
        flat = 6 * MONTHLY_DIVIDEND * (1 + (COUPON + 0.0025) / 12)
        self.assertGreater(arrears, flat)

    def test_first_missed_month_joins_at_face(self):
        config = make_config(total_months=1)
        *_, arrears, _flows = run(0.0, 0.0, [1.0], config)

        self.assertAlmostEqual(arrears, MONTHLY_DIVIDEND,
                               msg="accrual starts the month after the miss")

    def test_rate_steps_up_25bps_per_month_outstanding(self):
        """Month n outstanding accrues at coupon + n × 25bps."""
        config = make_config(total_months=3)
        *_, arrears, _flows = run(0.0, 0.0, [1.0] * 3, config)

        first = MONTHLY_DIVIDEND
        second = first * (1 + (COUPON + 0.0025) / 12) + MONTHLY_DIVIDEND
        third = second * (1 + (COUPON + 0.0050) / 12) + MONTHLY_DIVIDEND
        self.assertAlmostEqual(arrears, third, places=9)

    def test_rate_is_capped_at_the_max(self):
        """Long suspensions stop stepping up once the cap is reached."""
        months = 60
        config = make_config(total_months=months, compounded_dividend_max_rate=0.20)
        *_, arrears, _flows = run(0.0, 0.0, [1.0] * months, config)

        self.assertAlmostEqual(arrears, expected_arrears(months), places=4)

        # With no cap the balance must be strictly larger, proving the cap binds.
        uncapped = make_config(total_months=months, compounded_dividend_max_rate=1.0)
        *_, uncapped_arrears, _ = run(0.0, 0.0, [1.0] * months, uncapped)
        self.assertGreater(uncapped_arrears, arrears)

    def test_start_rate_tracks_the_coupon(self):
        """A higher coupon means a higher arrears accrual rate."""
        low = make_config(total_months=4, compounded_dividend_start_rate=0.10)
        high = make_config(total_months=4, compounded_dividend_start_rate=0.13)

        *_, low_arrears, _ = run(0.0, 0.0, [1.0] * 4, low)
        *_, high_arrears, _ = run(0.0, 0.0, [1.0] * 4, high)

        self.assertGreater(high_arrears, low_arrears)
        self.assertAlmostEqual(low_arrears, expected_arrears(4, start_rate=0.10), places=6)


class TestCatchUp(unittest.TestCase):
    def test_arrears_are_paid_before_the_current_coupon(self):
        config = make_config(total_months=2)
        # Month 1: gate shut, nothing paid. Month 2: gate open, plenty of Bitcoin.
        prices = [1.0, 100.0]
        months_paid, btc, _cash, arrears, flows = run(0.0, 100.0, prices, config)

        self.assertEqual(arrears, 0.0, "recovery should clear the arrears")
        self.assertEqual(months_paid, 1, "only month 2's own coupon counts as paid")
        # $100 arrears + $100 current coupon, all funded at $100/BTC.
        self.assertAlmostEqual(flows.sum(), 200.0)
        self.assertAlmostEqual(btc, 98.0)

    def test_clearing_arrears_resets_the_rate_clock(self):
        """After a full catch-up, the next miss starts at the floor again."""
        config = make_config(total_months=5)
        # Miss twice, recover and clear, then miss once more.
        prices = [1.0, 1.0, 100.0, 1.0, 1.0]
        *_, arrears, _flows = run(0.0, 100.0, prices, config)

        # The post-recovery run is two fresh missed months, not months 4 and 5
        # of a continuing suspension.
        self.assertAlmostEqual(arrears, expected_arrears(2), places=9)

    def test_partial_cash_pays_what_it_can_and_the_rest_stays_outstanding(self):
        config = make_config(total_months=3)
        months_paid, _btc, cash, arrears, flows = run(250.0, 0.0, [1.0] * 3, config)

        self.assertEqual(months_paid, 2)
        self.assertAlmostEqual(cash, 0.0)
        self.assertAlmostEqual(flows.sum(), 250.0)
        self.assertAlmostEqual(arrears, 50.0)


class TestConfigurationClaim(unittest.TestCase):
    """The netted claim the gate is measured against."""

    def test_claim_marks_sata_at_market_and_nets_out_strc(self):
        config = Configuration(
            sata_shares_outstanding=1_000_000,
            sata_market_price=90.0,
            strc_shares_held=100_000,
            strc_market_price=95.0,
            bitcoin_holdings=1.0,
            cash=0.0,
            discount_rate_annual=0.04,
        )

        self.assertAlmostEqual(config.total_par_value, 100_000_000.0)
        self.assertAlmostEqual(config.sata_market_claim, 90_000_000.0)
        self.assertAlmostEqual(config.strc_position_value, 9_500_000.0)
        self.assertAlmostEqual(config.coverage_claim_value, 80_500_000.0)

    def test_claim_falls_back_to_par_without_a_quote(self):
        config = Configuration(
            sata_shares_outstanding=1_000_000,
            sata_market_price=None,
            strc_shares_held=100_000,
            strc_market_price=None,
            bitcoin_holdings=1.0,
            cash=0.0,
            discount_rate_annual=0.04,
        )

        self.assertAlmostEqual(config.sata_market_claim, 100_000_000.0)
        self.assertAlmostEqual(config.strc_position_value, 0.0,
                              msg="an unmarked position must not net anything out")
        self.assertAlmostEqual(config.coverage_claim_value, 100_000_000.0)

    def test_compounded_start_rate_defaults_to_the_live_coupon(self):
        """Per the certificate the arrears rate is the regular dividend rate."""
        config = Configuration(
            sata_annual_dividend_rate=0.115,
            bitcoin_holdings=1.0,
            cash=0.0,
            discount_rate_annual=0.04,
        )
        self.assertAlmostEqual(config.compounded_dividend_start_rate, 0.115)

        pinned = Configuration(
            sata_annual_dividend_rate=0.115,
            compounded_dividend_start_rate=0.20,
            bitcoin_holdings=1.0,
            cash=0.0,
            discount_rate_annual=0.04,
        )
        self.assertAlmostEqual(pinned.compounded_dividend_start_rate, 0.20)

    def test_claim_never_goes_negative(self):
        config = Configuration(
            sata_shares_outstanding=1_000,
            sata_market_price=1.0,
            strc_shares_held=1_000_000,
            strc_market_price=100.0,
            bitcoin_holdings=1.0,
            cash=0.0,
            discount_rate_annual=0.04,
        )
        self.assertEqual(config.coverage_claim_value, 0.0)

    def test_to_dict_carries_the_claim_into_the_workers(self):
        config = Configuration(
            sata_shares_outstanding=1_000_000,
            sata_market_price=90.0,
            strc_shares_held=100_000,
            strc_market_price=95.0,
            bitcoin_holdings=1.0,
            cash=0.0,
            discount_rate_annual=0.04,
        )
        as_dict = config.to_dict()

        self.assertAlmostEqual(as_dict["coverage_claim_value"], 80_500_000.0)
        self.assertAlmostEqual(as_dict["strc_position_value"], 9_500_000.0)


class TestCashNetOfHeldPreferred(unittest.TestCase):
    """strategytracker reports the STRC position inside ASST's cash."""

    def test_position_is_stripped_out_of_reported_cash(self):
        from preferred_valuation import cash_net_of_held_preferred

        # 2026-08-07: tracker $202.664M vs the 10-Q's $154.9M cash + $48.0M STRC.
        self.assertAlmostEqual(
            cash_net_of_held_preferred(202_664_000.0, 48_000_000.0),
            154_664_000.0,
        )

    def test_unmarked_position_leaves_cash_alone(self):
        from preferred_valuation import cash_net_of_held_preferred

        self.assertAlmostEqual(cash_net_of_held_preferred(200.0, 0.0), 200.0)

    def test_cash_never_goes_negative(self):
        from preferred_valuation import cash_net_of_held_preferred

        self.assertEqual(cash_net_of_held_preferred(10.0, 100.0), 0.0)


if __name__ == "__main__":
    unittest.main()
