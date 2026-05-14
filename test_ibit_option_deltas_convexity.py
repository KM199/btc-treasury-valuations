"""
Regression: parallel spot+rate shock P&L dV ≈ Δ·dS + ½Γ·dS² + ρ·dr with dS, dr ∝ h.

Δ·dS and ρ·dr are odd in h; only ½Γ·dS² is even. With Γ≈0 from too-tight FD bumps on the CRR
tree, dV(+h) ≈ −dV(−h) (mirrored columns). american_delta_gamma uses a wider Γ bump so this
test can require material convexity on at least one liquid strike.
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_ibit_data():
    from strc_paths import OUTPUT_DIR

    for p in (OUTPUT_DIR / "ibit_data.json", ROOT / "ibit_data.json"):
        if p.is_file():
            return json.loads(p.read_text())
    return None


class TestIbitOptionDeltasConvexity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _load_ibit_data()

    def test_parallel_shock_has_even_gamma_contribution(self):
        if self.data is None:
            self.skipTest("ibit_data.json not present")
        from ibit_option_deltas import (
            DEFAULT_TREE_STEPS,
            _parse_valuation_datetime,
            american_delta_gamma,
            american_rho_bumped,
            implied_vol_bisection,
            option_mid,
            year_fraction_to_expiry,
        )

        data = self.data
        S = float(data["current_price"])
        od = data.get("options_data")
        self.assertIsInstance(od, dict)

        exp = sorted(data.get("expirations") or [])[-1]
        block = od.get(exp)
        self.assertIsInstance(block, dict)
        puts = block.get("puts") or []
        by_k = {float(p["strike"]): p for p in puts if "strike" in p}

        val = _parse_valuation_datetime(str(data.get("timestamp") or ""))
        T = year_fraction_to_expiry(val, date.fromisoformat(exp))
        h_shock = 0.5

        best_ratio = 0.0
        for K in (25.0, 30.0, 35.0, 40.0, 45.0):
            row = by_k.get(K)
            if row is None:
                continue
            mid = option_mid(row.get("bid"), row.get("ask"))
            if mid is None:
                continue
            r = float(row["risk_free_rate"])
            iv = implied_vol_bisection(
                mid, S, K, T, r, 0.0, n_steps=DEFAULT_TREE_STEPS, is_call=False
            )
            if iv is None:
                continue
            dlt, gam = american_delta_gamma(
                S, K, T, r, 0.0, iv, n_steps=DEFAULT_TREE_STEPS, is_call=False
            )
            if dlt is None or gam is None:
                continue
            rho = american_rho_bumped(
                S, K, T, r, 0.0, iv, n_steps=DEFAULT_TREE_STEPS, is_call=False
            )
            if rho is None:
                rho = 0.0

            def d_pi(h: float) -> float:
                dS, dr = h * S, h * r
                return dlt * dS + 0.5 * gam * dS * dS + rho * dr

            up, dn = d_pi(h_shock), d_pi(-h_shock)
            residue = abs(up + dn)
            scale = max(abs(up), abs(dn), 1e-12)
            best_ratio = max(best_ratio, residue / scale)

        self.assertGreater(
            best_ratio,
            0.02,
            "|dV(+h)+dV(-h)| / max(|dV|) should exceed 2% for some strike (Γ convexity)",
        )

    def test_gamma_magnitude_atm_strike(self):
        if self.data is None:
            self.skipTest("ibit_data.json not present")
        from ibit_option_deltas import (
            DEFAULT_TREE_STEPS,
            _parse_valuation_datetime,
            american_delta_gamma,
            implied_vol_bisection,
            option_mid,
            year_fraction_to_expiry,
        )

        data = self.data
        S = float(data["current_price"])
        od = data["options_data"]
        exp = sorted(data["expirations"])[-1]
        puts = {float(p["strike"]): p for p in od[exp]["puts"] if "strike" in p}
        val = _parse_valuation_datetime(str(data["timestamp"]))
        T = year_fraction_to_expiry(val, date.fromisoformat(exp))

        row = puts.get(35.0)
        self.assertIsNotNone(row)
        mid = option_mid(row["bid"], row["ask"])
        self.assertIsNotNone(mid)
        r = float(row["risk_free_rate"])
        iv = implied_vol_bisection(
            mid, S, 35.0, T, r, 0.0, n_steps=DEFAULT_TREE_STEPS, is_call=False
        )
        self.assertIsNotNone(iv)
        _d, gam = american_delta_gamma(
            S, 35.0, T, r, 0.0, iv, n_steps=DEFAULT_TREE_STEPS, is_call=False
        )
        self.assertIsNotNone(gam)
        self.assertGreater(abs(gam), 1e-4, "material Γ at ~ATM long-dated put")

    def test_full_repricing_long_put_loses_when_spot_up(self):
        """Notebook-style parallel shock: same σ, bump S and r; long put must lose when IBIT rises."""
        if self.data is None:
            self.skipTest("ibit_data.json not present")
        from ibit_option_deltas import (
            DEFAULT_DIV_YIELD,
            DEFAULT_TREE_STEPS,
            american_price_crr,
            _parse_valuation_datetime,
            year_fraction_to_expiry,
        )

        data = self.data
        S0 = float(data["current_price"])
        od = data["options_data"]
        exp = sorted(data["expirations"])[-1]
        val = _parse_valuation_datetime(str(data["timestamp"]))
        T = year_fraction_to_expiry(val, date.fromisoformat(exp))
        for K in (10.0, 45.0):
            row = next(p for p in od[exp]["puts"] if float(p["strike"]) == K)
            iv = row.get("implied_volatility")
            self.assertIsNotNone(iv)
            self.assertGreater(float(iv), 0.0)
            ri = float(row["risk_free_rate"])
            sig = float(iv)
            V0 = american_price_crr(
                S0, K, T, ri, DEFAULT_DIV_YIELD, sig,
                n_steps=DEFAULT_TREE_STEPS, is_call=False,
            )
            h = 0.5
            V1 = american_price_crr(
                S0 * (1.0 + h), K, T, ri * (1.0 + h), DEFAULT_DIV_YIELD, sig,
                n_steps=DEFAULT_TREE_STEPS, is_call=False,
            )
            self.assertLess(
                V1 - V0,
                0.0,
                f"long put K={K}: +50% spot parallel should reduce option value",
            )


if __name__ == "__main__":
    unittest.main()
