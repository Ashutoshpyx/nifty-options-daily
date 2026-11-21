"""Run:  python -m unittest tests.test_calcs -v"""
import unittest

import numpy as np
import pandas as pd

from src import advanced as X
from src import analysis as A

F, K, T, R, SIG = 25000.0, 25200.0, 7 / 365, 0.065, 0.14


class TestOptionMath(unittest.TestCase):
    def test_put_call_parity(self):
        c, p = A.b76(F, K, T, SIG, R, "CE"), A.b76(F, K, T, SIG, R, "PE")
        self.assertAlmostEqual(c - p, np.exp(-R * T) * (F - K), places=8)

    def test_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):
            A.b76(F, K, T, SIG, R, "XX")
        with self.assertRaises(ValueError):
            A.b76(F, K, 0, SIG, R, "CE")

    def test_iv_round_trip_and_bounds(self):
        for cp in ("CE", "PE"):
            px = A.b76(F, K, T, 0.17, R, cp)
            self.assertAlmostEqual(A.implied_vol(px, F, K, T, R, cp), 0.17, places=6)
        self.assertTrue(np.isnan(A.implied_vol(F * 1.1, F, K, T, R, "CE")))      # above upper bound
        self.assertTrue(np.isnan(A.implied_vol(0.01, F, 24000, T, R, "CE")))     # below intrinsic

    def test_delta_identity(self):
        dc, dp = A.delta(F, K, T, SIG, R, "CE"), A.delta(F, K, T, SIG, R, "PE")
        self.assertAlmostEqual(dc - dp, np.exp(-R * T), places=8)

    def test_greeks_match_finite_difference(self):
        g = X.greeks(F, K, T, SIG, "CE")
        up = A.b76(F, K, T, SIG + 0.01, R, "CE") - A.b76(F, K, T, SIG, R, "CE")
        self.assertAlmostEqual(g["vega"], up, places=10)
        self.assertLess(g["theta"], 0)                       # a long option loses value with time
        self.assertGreater(g["gamma"], 0)


class TestStructures(unittest.TestCase):
    def chain(self):
        return pd.DataFrame({"ce_px": {24900.0: 220.0, 25000.0: 160.0, 25100.0: 110.0},
                             "pe_px": {24900.0: 90.0, 25000.0: 130.0, 25100.0: 185.0}})

    def test_bull_call_debit_and_bear_call_credit(self):
        bc = A.vertical(self.chain(), "CE", 24900.0, 25100.0, 65)
        self.assertAlmostEqual(bc["net"], -110.0)
        self.assertAlmostEqual(bc["max_loss"], 110.0)
        self.assertAlmostEqual(bc["max_profit"], 90.0)
        self.assertAlmostEqual(bc["be"], 25010.0)
        br = A.vertical(self.chain(), "CE", 25100.0, 24900.0, 65)
        self.assertAlmostEqual(br["net"], 110.0)

    def test_bull_put_credit_and_bear_put_debit(self):
        bp = A.vertical(self.chain(), "PE", 24900.0, 25100.0, 65)
        self.assertAlmostEqual(bp["net"], 95.0)
        self.assertAlmostEqual(bp["be"], 25005.0)
        self.assertAlmostEqual(bp["max_loss"], 105.0)
        brp = A.vertical(self.chain(), "PE", 25100.0, 24900.0, 65)
        self.assertAlmostEqual(brp["net"], -95.0)

    def test_inconsistent_quotes_rejected(self):
        bad = self.chain()
        bad.loc[25100.0, "ce_px"] = 300.0                    # far call dearer than near: not a bull call
        self.assertIsNone(A.vertical(bad, "CE", 24900.0, 25100.0, 65))


class TestHistoryAndOI(unittest.TestCase):
    def test_forward_window_indexing(self):
        idx = pd.bdate_range("2024-01-01", periods=120)
        c = np.linspace(100, 220, 120)
        h = pd.DataFrame({"n_open": c, "n_close": c, "n_high": c + 1, "n_low": c - 1, "vix": 15.0}, index=idx)
        w = X.window_stats(h, 2)
        self.assertAlmostEqual(w["end"][0], c[2] / c[0] - 1)                  # looks forward, not back
        self.assertAlmostEqual(w["up"][0], (c[2] + 1) / c[0] - 1)
        self.assertAlmostEqual(w["dn"][0], 1 - (c[1] - 1) / c[0])

    def test_missing_vix_keeps_session_spacing(self):
        idx = pd.bdate_range("2024-01-01", periods=120)
        c = np.linspace(100, 220, 120)
        h = pd.DataFrame({"n_open": c, "n_close": c, "n_high": c + 1, "n_low": c - 1, "vix": 15.0}, index=idx)
        h.iloc[40, h.columns.get_loc("vix")] = np.nan
        w = X.window_stats(h, 2)
        self.assertEqual(len(w["end"]), 118)                       # no session removed
        self.assertAlmostEqual(w["end"][39], c[41] / c[39] - 1)    # still exactly 2 sessions ahead
        self.assertTrue(np.isnan(w["vix"][40]))

    def test_confluence_empty(self):
        self.assertEqual(X.confluence({}, 25000.0), [])

    def test_new_strike_counts_as_added_oi(self):
        e = pd.Timestamp("2026-12-01")
        def snap(rows):
            return pd.DataFrame([dict(XpryDt=e, OptnTp="CE", StrkPric=k, OpnIntrst=v) for k, v in rows])
        now, then = snap([(25500, 900), (25600, 500)]), snap([(25500, 400)])
        # add a put row so both sides exist
        now = pd.concat([now, snap([(24500, 300)]).assign(OptnTp="PE")])
        then = pd.concat([then, snap([(24500, 100)]).assign(OptnTp="PE")])
        out = X.oi_build_since(now, then, e, 25000.0)
        self.assertIn((25600.0, 500.0), out["calls_added"])


class TestAuditThree(unittest.TestCase):
    def test_confluence_cluster_span_limited(self):
        z = X.confluence({"a": 100.0, "b": 135.0, "c": 170.0}, 150.0, width=40)
        for cl in z:
            self.assertLessEqual(max(cl["levels"]) - min(cl["levels"]) if "levels" in cl else 0, 40)
        self.assertTrue(all(cl["n"] <= 2 for cl in z))             # 100,135,170 must not chain into one

    def test_trading_days_with_holiday(self):
        d, e = pd.Timestamp("2026-11-20"), pd.Timestamp("2026-11-24")     # Fri -> Tue
        self.assertEqual(X.trading_days_to(d, e, holidays=[]), 2)
        self.assertEqual(X.trading_days_to(d, e, holidays=[pd.Timestamp("2026-11-23").date()]), 1)

    def test_bias_skips_missing_inputs(self):
        ts = dict(close=100.0, ema20=np.nan, ema50=90.0, macd_hist=1.0, rsi=np.nan)
        pts, _, items = A.bias_items(ts, dict(pcr_oi=np.nan), None, None)
        self.assertEqual([i["label"] for i in items], ["MACD histogram"])

    def test_calendar_scenario_sanity(self):
        near = dict(spot=25000.0, Tm=7 / 365)
        far = dict(spot=25000.0, Tm=14 / 365)
        rows = A.calendar_scenarios(near, far, 25000.0, "CE", 80.0, 65, 0.14, moves=(-3, 0, 3), iv_shifts=(0.0,))
        pnl = rows[0][1]
        self.assertGreater(pnl[1], pnl[0])           # tent: best near the strike
        self.assertGreater(pnl[1], pnl[2])
        # at the strike with far IV unchanged the near leg is worth 0 at expiry, so P&L = far value - debit
        far_val = A.b76(25000.0 * np.exp(A.RISK_FREE * 7 / 365), 25000.0, 7 / 365, 0.14, A.RISK_FREE, "CE")
        self.assertAlmostEqual(pnl[1], (far_val - 80.0) * 65, places=6)


class TestAuditFour(unittest.TestCase):
    def test_confluence_edge_cases(self):
        self.assertEqual(len(X.confluence({"a": 100.0, "b": 100.0}, 90.0, width=0)), 1)        # duplicates cluster at zero width
        self.assertEqual(X.confluence({"a": 100.0, "b": 101.0}, 90.0, width=0), [])             # zero width: only equal levels
        with self.assertRaises(ValueError):
            X.confluence({"a": 1.0}, 1.0, width=-5)
        tie = X.confluence({"a": 100.0, "b": 140.0, "c": 140.0}, 90.0, width=40)
        self.assertEqual(tie[0]["n"], 3)                                                        # span exactly 40 is allowed

    def test_forward_delta_gamma_vs_finite_difference(self):
        h = 1.0
        g = X.greeks(F, K, T, SIG, "CE")
        up, mid, dn = (A.b76(F + h, K, T, SIG, R, "CE"), A.b76(F, K, T, SIG, R, "CE"), A.b76(F - h, K, T, SIG, R, "CE"))
        self.assertAlmostEqual(g["delta"], (up - dn) / (2 * h), places=6)
        self.assertAlmostEqual(g["gamma"], (up - 2 * mid + dn) / h ** 2, places=6)

    def test_wilson_range(self):
        lo, hi = X.wilson(0.10, 100)
        self.assertTrue(0 < lo < 0.10 < hi < 0.25)
        self.assertTrue(np.isnan(X.wilson(0.1, 0)[0]))

    def test_schema_and_duplicates_rejected(self):
        from src import data as D
        with self.assertRaises(ValueError):
            D.prepare_nifty(pd.DataFrame({"TckrSymb": ["NIFTY"]}))
        row = dict(TradDt="2026-11-20", FinInstrmTp="IDO", TckrSymb="NIFTY", XpryDt="2026-12-01", StrkPric=25000.0, OptnTp="CE",
                   ClsPric=1.0, PrvsClsgPric=1.0, UndrlygPric=25000.0, SttlmPric=1.0, OpnIntrst=10, ChngInOpnIntrst=0,
                   TtlTradgVol=1, NewBrdLotQty=65)
        with self.assertRaises(ValueError):
            D.prepare_nifty(pd.DataFrame([row, row]))

    def test_expired_contract_rejected(self):
        e = pd.Timestamp("2026-11-20")
        row = dict(XpryDt=e, OptnTp="CE", StrkPric=25000.0, OpnIntrst=1, ChngInOpnIntrst=0, TtlTradgVol=1, SttlmPric=10.0,
                   ClsPric=10.0, PrvsClsgPric=10.0, UndrlygPric=25000.0, NewBrdLotQty=65)
        with self.assertRaises(ValueError):
            A.build_chain(pd.DataFrame([row, {**row, "OptnTp": "PE"}]), e, "2026-11-20")


class TestAuditFive(unittest.TestCase):
    ROW = dict(TradDt="2026-11-20", FinInstrmTp="IDO", TckrSymb="NIFTY", XpryDt="2026-12-01", StrkPric=25000.0, OptnTp="CE",
               ClsPric=1.0, PrvsClsgPric=1.0, UndrlygPric=25000.0, SttlmPric=1.0, OpnIntrst=10.0, ChngInOpnIntrst=0.0,
               TtlTradgVol=1.0, NewBrdLotQty=65)

    def rows(self, **over):
        r1 = {**self.ROW, **over}
        r2 = {**r1, "OptnTp": "PE"}
        shared = {k: v for k, v in over.items() if k in ("XpryDt", "NewBrdLotQty", "TradDt")}
        fut = {**self.ROW, **shared, "FinInstrmTp": "IDF", "OptnTp": "", "StrkPric": np.nan, "SttlmPric": 25010.0,
               "OpnIntrst": 1000.0, "ChngInOpnIntrst": 10.0}
        return pd.DataFrame([r1, r2, fut])

    def test_valid_file_passes(self):
        from src import data as D
        opts, _ = D.prepare_nifty(self.rows())
        self.assertEqual(len(opts), 2)       # two options; the future is returned separately

    def test_bad_inputs_each_rejected(self):
        from src import data as D
        bad = [dict(OpnIntrst=-500.0), dict(TtlTradgVol=-2.0), dict(NewBrdLotQty=0), dict(NewBrdLotQty=65.5),
               dict(SttlmPric=-1.0), dict(StrkPric=0.0), dict(OpnIntrst=10.0, ChngInOpnIntrst=50.0)]
        for over in bad:
            with self.assertRaises(ValueError, msg=str(over)):
                D.prepare_nifty(self.rows(**over))

    def test_mixed_lots_in_one_expiry_rejected(self):
        from src import data as D
        df = self.rows()
        df.loc[0, "NewBrdLotQty"] = 50
        with self.assertRaises(ValueError):
            D.prepare_nifty(df)

    def test_mixed_trade_dates_rejected(self):
        from src import data as D
        df = self.rows()
        df.loc[0, "TradDt"] = "2026-11-19"
        with self.assertRaises(ValueError):
            D.prepare_nifty(df)

    def test_different_lots_across_expiries_allowed_but_calendar_blocked(self):
        from src import data as D
        a, b = self.rows(), self.rows(XpryDt="2026-12-08", NewBrdLotQty=75)
        opts, _ = D.prepare_nifty(pd.concat([a, b], ignore_index=True))
        self.assertEqual(opts["NewBrdLotQty"].nunique(), 2)
        ch = pd.DataFrame({"ce_px": {25000.0: 100.0}, "pe_px": {25000.0: 90.0}, "ce_iv": {25000.0: .14}, "pe_iv": {25000.0: .14}})
        near, far = dict(lot=65, F=25000.0), dict(lot=75, F=25000.0)
        self.assertEqual(A.calendar_table(ch, ch, near, far, 25000.0), [])

    def test_spot_delta_gamma_vs_finite_difference(self):
        S0, h = 24980.0, 1.0
        k = F / S0                                    # forward = spot grown at the carry rate
        g = X.greeks(F, K, T, SIG, "CE", spot=S0)
        price = lambda S: A.b76(S * k, K, T, SIG, R, "CE")
        self.assertAlmostEqual(g["delta"], (price(S0 + h) - price(S0 - h)) / (2 * h), places=6)
        self.assertAlmostEqual(g["gamma"], (price(S0 + h) - 2 * price(S0) + price(S0 - h)) / h ** 2, places=6)
        self.assertNotAlmostEqual(g["delta"], g["delta_fwd"], places=4)       # the two conventions differ

    def test_expiry_on_holiday_or_weekend_rejected(self):
        hol = [pd.Timestamp("2026-11-24").date()]
        A.validate_expiries([pd.Timestamp("2026-11-23")], hol)              # Monday, fine
        with self.assertRaises(ValueError):
            A.validate_expiries([pd.Timestamp("2026-11-24")], hol)
        with self.assertRaises(ValueError):
            A.validate_expiries([pd.Timestamp("2026-11-22")], hol)          # Sunday

    def test_shipped_calendar_complete(self):
        hol, years = X.load_calendar()
        self.assertIn(2026, years)
        self.assertEqual(sum(1 for d in hol if d.year == 2026), 16)       # 15 base + 15 Jan F&O closure
        self.assertIn(pd.Timestamp("2026-01-15").date(), hol)
        self.assertEqual(X.trading_days_to("2026-01-14", "2026-01-16", hol), 1)
        self.assertIn(pd.Timestamp("2026-11-24").date(), hol)


class TestAuditSix(unittest.TestCase):
    def frame(self, mutate=None):
        base = dict(TestAuditFive.ROW)
        c, p = {**base}, {**base, "OptnTp": "PE"}
        f = {**base, "FinInstrmTp": "IDF", "OptnTp": "", "StrkPric": np.nan, "SttlmPric": 25010.0, "OpnIntrst": 1000.0, "ChngInOpnIntrst": 10.0}
        df = pd.DataFrame([c, p, f])
        if mutate:
            mutate(df)
        return df

    def test_clean_frame_passes(self):
        from src import data as D
        D.prepare_nifty(self.frame())

    def test_each_corruption_rejected(self):
        from src import data as D
        def set_(r, col, v):
            return lambda d: d.__setitem__(col, d[col].astype(object)) or d.loc.__setitem__((r, col), v)
        cases = {
            "inf_oi": set_(0, "OpnIntrst", np.inf),
            "nan_oi_change": set_(0, "ChngInOpnIntrst", np.nan),
            "nan_volume": set_(1, "TtlTradgVol", np.nan),
            "negative_futures_oi": set_(2, "OpnIntrst", -20.0),
            "inconsistent_underlying": set_(1, "UndrlygPric", 25375.0),
            "text_in_numeric_field": set_(0, "OpnIntrst", "abc"),
        }
        for name, fn in cases.items():
            with self.assertRaises(ValueError, msg=name):
                D.prepare_nifty(self.frame(fn))

    def test_duplicate_futures_rejected(self):
        from src import data as D
        df = self.frame()
        df = pd.concat([df, df.iloc[[2]]], ignore_index=True)
        with self.assertRaises(ValueError):
            D.prepare_nifty(df)


class TestTechnicals(unittest.TestCase):
    def test_rsi_defined_for_unbroken_gains_and_flat(self):
        idx = pd.bdate_range("2024-01-01", periods=60)
        up = pd.DataFrame({"n_open": 1.0, "n_close": np.arange(100, 160.0), "n_high": np.arange(101, 161.0), "n_low": np.arange(99, 159.0)}, index=idx)
        self.assertEqual(A.technicals(up)["rsi"].iloc[-1], 100.0)
        flat = up.assign(n_close=100.0, n_high=101.0, n_low=99.0)
        self.assertEqual(A.technicals(flat)["rsi"].iloc[-1], 50.0)


if __name__ == "__main__":
    unittest.main()
