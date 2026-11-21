import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from src import advanced as X, analysis as A, build_report as B, data as D


class TestAuditControls(unittest.TestCase):
    def test_calendar_combines_all_four_legs(self):
        near = pd.DataFrame({"ce_px": [30.], "pe_px": [20.], "ce_vol": [1], "pe_vol": [2],
                             "ce_iv": [.15], "pe_iv": [.17]}, index=[1000])
        far = near.assign(ce_px=45., pe_px=40.)
        n = dict(F=1000., spot=1000., Tm=3/365, lot=65)
        f = {**n, "Tm": 11/365}
        row, = X.double_calendars(near, far, n, f, [(1000, 1000)])
        self.assertEqual(row["debit"], -15*65)
        unchanged = row["scenarios"][1][1][3]
        t = f["Tm"] - n["Tm"]
        forward = 1000*np.exp(A.RISK_FREE*t)
        expected = sum(A.b76(forward, 1000, t, iv, A.RISK_FREE, kind)
                       for kind, iv in [("CE", .15), ("PE", .17)])
        self.assertAlmostEqual(unchanged, (expected+15)*65)
        self.assertEqual(X.double_calendars(near, far.assign(pe_vol=0), n, f, [(1000, 1000)]), [])

    def test_clipped_snapshot_has_unknown_strikes(self):
        expiry = pd.Timestamp("2026-11-23")
        now = pd.DataFrame({"XpryDt": expiry, "OptnTp": ["CE", "PE", "PE"],
                            "StrkPric": [26100, 25000, 22000], "OpnIntrst": [10, 15, 5290025]})
        old = now.iloc[:2].copy()
        old.attrs["full_coverage"] = False
        self.assertEqual(X.oi_build_since(now, old, expiry, 25800)["puts_added"], [])

    def test_cash_requires_current_reconciled_sessions(self):
        dates = pd.bdate_range("2026-11-16", periods=5).strftime("%Y-%m-%d")
        log = pd.DataFrame({"fii_buy": 11., "fii_sell": 10., "fii_net": 1.}, index=dates)
        day = dt.date(2026, 11, 20)
        self.assertEqual(D.cash_window(log, day, 5, []), 5.)
        for partial in (log.iloc[:-1], log.drop(dates[1]), log.assign(fii_net=8.)):
            self.assertIsNone(D.cash_window(partial, day, 5, []))
        bad = dict(category="FII", date="20-Nov-2026", buyValue=20, sellValue=10, netValue=50)
        with self.assertRaises(ValueError):
            D.parse_cash_rows([bad])

    def test_event_states_and_coverage(self):
        self.assertEqual([A.event_check("events", x)["state"] for x in [None, [], ["RBI"]]], [0, 1, -1])
        with tempfile.TemporaryDirectory() as temp, patch.object(D, "PROJECT", Path(temp)):
            data = Path(temp, "data")
            data.mkdir()
            day, expiry = dt.date(2026, 11, 20), pd.Timestamp("2026-11-23")
            (data / "events.csv").write_text("date,event,impact\n")
            self.assertFalse(D.event_coverage(D.load_events(), day, expiry))
            meta = {"source": "test calendar", "as_of": "2026-11-19", "from": "2026-11-19", "through": "2026-11-23"}
            (data / "event_coverage.json").write_text(json.dumps(meta))
            self.assertTrue(D.event_coverage(D.load_events(), day, expiry))
            (data / "events.csv").unlink()
            self.assertFalse(D.event_coverage(D.load_events(), day, expiry))

    def test_expiry_and_master_controls(self):
        dates = pd.to_datetime(["2026-12-01", "2026-12-08", "2026-12-15", "2026-12-29"])
        options = pd.DataFrame({"XpryDt": dates[:-1]})
        with self.assertRaisesRegex(ValueError, "Missing option chain"):
            A.pick_expiries(options, "2026-11-30", [], set(dates), {dates[-1]})
        with self.assertRaises(ValueError):
            A.validate_expiries([pd.Timestamp("2026-12-02")], [])
        with self.assertRaises(ValueError):
            A.pick_expiries(options, "2026-11-30", [])
        master = pd.DataFrame([dict(FinInstrmId=1, FinInstrmNm="OPTIDX", XpryDt=dates[0], StrkPric=25000,
                                    OptnTp="CE", NewBrdLotQty=65, StockNm="NIFTY26D0125000CE")])
        with self.assertRaisesRegex(ValueError, "disagree"):
            D.verify_master(master, master.assign(NewBrdLotQty=75), master.iloc[:0])

    def test_flat_moves_and_missing_band(self):
        f = pd.DataFrame([dict(XpryDt=pd.Timestamp("2026-11-23"), SttlmPric=100., PrvsClsgPric=100.,
                               ChngInOpnIntrst=0, OpnIntrst=10)])
        future = A.futures_view(f, "2026-11-20", 100.)
        self.assertEqual(future["label"], "Neutral")
        tech = dict(close=100., ema20=100., ema50=100., macd_hist=0., rsi=50.)
        self.assertEqual(A.bias_items(tech, {"pcr_oi": 1.}, future, None)[0], 0)
        self.assertTrue(np.isnan(X.band_touch({}, np.nan)).all())


class TestPublication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.project = Path(cls.temp.name)
        shutil.copytree(D.PROJECT / "data", cls.project / "data", ignore=shutil.ignore_patterns("verified_v1"))
        generator = cls.project / "make_demo_data.py"
        shutil.copy(Path(__file__).with_name("make_demo_data.py"), generator)
        subprocess.run([sys.executable, str(generator)], check=True, stdout=subprocess.DEVNULL)
        cls.demo = cls.project / "demo"

    def args(self, tag):
        return Namespace(bhav_file=self.demo / f"bhav_{tag}.csv", hist_file=self.demo / "hist.csv",
                         part_file=self.demo / f"part_{tag}.csv", cash_file=self.demo / f"cash_{tag}.json",
                         contract_file=None, date=None, demo=True, force=True)

    def test_backfill_bad_inputs_and_publication(self):
        with patch.object(D, "PROJECT", self.project), contextlib.redirect_stdout(io.StringIO()):
            args = self.args("20261120")
            B.build(args)
            page = D.ROOT / "docs/index.html"
            brief = D.ROOT / "reports/latest.md"
            original = page.read_bytes(), brief.read_bytes()
            self.assertIn(b"SYNTHETIC DEMO", original[0])
            self.assertIn(b"SYNTHETIC DEMO", original[1])
            self.assertIn(b"Coverage unverified", original[0])
            self.assertIn(b"5d unavailable", original[0])
            self.assertFalse((self.project / "docs/index.html").exists())
            B.build(self.args("20261119"))
            self.assertEqual(original, (page.read_bytes(), brief.read_bytes()))
            older = (page.parent / "2026-11-19.html").read_text()
            self.assertNotIn(">2026-11-20<", older)
            raw19 = pd.read_csv(self.args("20261119").bhav_file)
            expiry = raw19[(raw19.TckrSymb == "NIFTY") & (raw19.FinInstrmTp == "IDO")
                           & (raw19.XpryDt == "2026-11-23")]
            spot = expiry.UndrlygPric.iloc[0]
            strike = expiry.loc[(expiry.StrkPric - spot).abs().idxmin(), "StrkPric"]
            premium = expiry.loc[expiry.StrkPric == strike, "SttlmPric"].sum()
            self.assertNotEqual(spot, strike)
            self.assertIn(f"{strike-premium:,.2f} - {strike+premium:,.2f}", older)
            args.date = "2026-11-19"
            with self.assertRaisesRegex(ValueError, "Requested"):
                B.build(args)
            args.date = "2026-11-20"
            raw = pd.read_csv(args.bhav_file)
            near = (raw.TckrSymb == "NIFTY") & (raw.FinInstrmTp == "IDO") & (raw.XpryDt == "2026-11-23")
            args.bhav_file = self.project / "mutation.csv"
            # An option settled on the report date must not pollute aggregate OI.
            expired = raw[(raw.TckrSymb == "NIFTY") & (raw.OptnTp == "PE")].iloc[[0]].copy()
            expired.loc[:, "XpryDt"] = "2026-11-20"
            expired.loc[:, "OpnIntrst"] = 10**13
            pd.concat([raw, expired]).to_csv(args.bhav_file, index=False)
            B.build(args)
            def pcr_ticker(html):
                return html.split(b"<small>PCR OI</small>", 1)[1].split(b"</div>", 1)[0]
            self.assertEqual(pcr_ticker(page.read_bytes()), pcr_ticker(original[0]))
            original = page.read_bytes(), brief.read_bytes()
            invalid = raw.copy()
            invalid.loc[near & (raw.StrkPric == 25000), ["SttlmPric", "ClsPric"]] = 50000.
            invalid.to_csv(args.bhav_file, index=False)
            with self.assertRaisesRegex(ValueError, "invalid ATM"):
                B.build(args)
            raw.loc[near & raw.StrkPric.between(24500, 25500), "TtlTradgVol"] = 0
            raw.to_csv(args.bhav_file, index=False)
            with self.assertRaisesRegex(ValueError, "paired traded strikes"):
                B.build(args)
            self.assertEqual(original, (page.read_bytes(), brief.read_bytes()))
            B.build(self.args("20261120"))
            self.assertIn(b"20 Nov", page.read_bytes())
