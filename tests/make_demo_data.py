"""Creates FAKE data so you can test the pipeline without NSE (6 sessions, so day-on-day sections fill in).
   python tests/make_demo_data.py
   python tests/run_demo.py
The numbers are invented; only the file layouts mimic NSE's.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

rng = np.random.default_rng(7)
OUT = Path(__file__).parent / "demo"
OUT.mkdir(exist_ok=True)
DAYS = pd.to_datetime(["2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"])


def b76(F, K, T, s, cp):
    d1 = (np.log(F / K) + 0.5 * s * s * T) / (s * np.sqrt(T)); d2 = d1 - s * np.sqrt(T)
    return F * norm.cdf(d1) - K * norm.cdf(d2) if cp == "CE" else K * norm.cdf(-d2) - F * norm.cdf(-d1)


# ---- price history (600 sessions)
days = pd.bdate_range(end=DAYS[-1], periods=600)
vix = [13.5]
for _ in range(len(days) - 1):
    vix.append(max(9.5, vix[-1] + 0.12 * (14 - vix[-1]) + rng.normal(0, 0.45)))
vix = np.array(vix)
ret = rng.normal(0.0004, 0.0075, len(days))
close = 25000 * np.exp(np.cumsum(ret) - np.cumsum(ret)[-1])
spread = np.abs(rng.normal(0.007, 0.002, len(days))) * close
hist = pd.DataFrame({"n_open": close * (1 + rng.normal(0, 0.002, len(days))), "n_close": close}, index=days)
hist["n_high"] = hist[["n_open", "n_close"]].max(axis=1) + spread * 0.35
hist["n_low"] = hist[["n_open", "n_close"]].min(axis=1) - spread * 0.35
hist["vix"] = vix
hist.index.name = "date"
hist[["n_open", "n_high", "n_low", "n_close", "vix"]].to_csv(OUT / "hist.csv")

expiries = pd.to_datetime(["2026-11-17", "2026-11-23", "2026-12-01", "2026-12-08", "2026-12-15", "2026-12-22",
                           "2026-12-29", "2027-01-25", "2027-02-23"])
strikes = np.arange(21000, 29001, 50)
fii_long, fii_short = 160000, 110000
for D_ in DAYS:
    spot = float(hist.loc[D_, "n_close"]); v = float(hist.loc[D_, "vix"]) / 100
    rows = []
    for e in expiries:
        dte = (e - D_).days
        if dte < 1:
            continue
        T = dte / 365
        atm_iv = v * 0.93 + 0.008 * (1 - np.exp(-dte / 40)) - 0.01 * np.exp(-dte / 25)
        F = spot * (1 + 0.065 * T)
        for k in strikes:
            m = np.log(k / F)
            iv = atm_iv + (-0.6 * m if m < 0 else -0.15 * m) + 1.8 * m * m
            for cp in ("CE", "PE"):
                px = max(round(b76(F, k, T, iv, cp) * 20) / 20, 0.05)
                prev = max(px * (1 + rng.normal(0, 0.06)), 0.05)
                if px < 0.3 and abs(m) > 0.1:
                    continue
                wall = (4.0 if k % 500 == 0 else 1.0) * np.exp(-((k - (spot - 500 if cp == "PE" else spot + 500)) / 700) ** 2)
                oi = int(abs(rng.normal(1, 0.35)) * 6e5 * (wall + 0.08) * (1.6 if dte < 10 else 0.7) / (1 + dte / 40))
                rows.append(dict(TradDt=D_.strftime("%Y-%m-%d"), BizDt=D_.strftime("%Y-%m-%d"), Sgmt="FO", Src="NSE",
                                 FinInstrmTp="IDO", FinInstrmId=0, ISIN="", TckrSymb="NIFTY", SctySrs="",
                                 XpryDt=e.strftime("%Y-%m-%d"), FininstrmActlXpryDt=e.strftime("%Y-%m-%d"),
                                 StrkPric=float(k), OptnTp=cp, FinInstrmNm="x", OpnPric=px, HghPric=px, LwPric=px,
                                 ClsPric=px, LastPric=px, PrvsClsgPric=round(prev, 2), UndrlygPric=spot, SttlmPric=px,
                                 OpnIntrst=oi, ChngInOpnIntrst=int(rng.normal(0, oi * 0.12)),
                                 TtlTradgVol=int(oi * abs(rng.normal(0.6, 0.3))), TtlTrfVal=0, TtlNbOfTxsExctd=0,
                                 SsnId="F1", NewBrdLotQty=65, Rmks=""))
        fpx = round(F, 2)
        rows.append(dict(TradDt=D_.strftime("%Y-%m-%d"), BizDt=D_.strftime("%Y-%m-%d"), Sgmt="FO", Src="NSE",
                         FinInstrmTp="IDF", FinInstrmId=0, ISIN="", TckrSymb="NIFTY", SctySrs="",
                         XpryDt=e.strftime("%Y-%m-%d"), FininstrmActlXpryDt=e.strftime("%Y-%m-%d"), StrkPric=np.nan,
                         OptnTp="", FinInstrmNm="NIFTYFUT", OpnPric=fpx, HghPric=fpx, LwPric=fpx, ClsPric=fpx,
                         LastPric=fpx, PrvsClsgPric=fpx - 40, UndrlygPric=spot, SttlmPric=fpx, OpnIntrst=900000,
                         ChngInOpnIntrst=25000, TtlTradgVol=100000, TtlTrfVal=0, TtlNbOfTxsExctd=0, SsnId="F1",
                         NewBrdLotQty=65, Rmks=""))
    rows.append({**rows[0], "TckrSymb": "BANKNIFTY"})
    tag = D_.strftime("%Y%m%d")
    pd.DataFrame(rows).to_csv(OUT / f"bhav_{tag}.csv", index=False)

    # participant-wise OI in NSE's layout (title line first)
    fii_long += int(rng.normal(3000, 6000)); fii_short += int(rng.normal(0, 6000))
    hdr = ("Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short,"
           "Option Index Call Long,Option Index Put Long,Option Stock Call Long,Option Stock Put Long,"
           "Option Index Call Short,Option Index Put Short,Option Stock Call Short,Option Stock Put Short,"
           "Total Long Contracts,Total Short Contracts")
    def line(n, fl, fs, cl, pl, cs, ps): return f"{n},{fl},{fs},0,0,{cl},{pl},0,0,{cs},{ps},0,0,0,0"
    txt = [f"Participant wise Open Interest as on {D_:%b %d, %Y}", hdr,
           line("Client", 90000, 140000, 400000, 350000, 300000, 330000),
           line("DII", 30000, 20000, 20000, 90000, 15000, 25000),
           line("FII", fii_long, fii_short, 180000 + int(rng.normal(0, 9000)), 150000, 170000, 190000 + int(rng.normal(0, 9000))),
           line("Pro", 120000, 110000, 500000, 480000, 520000, 500000), line("TOTAL", 0, 0, 0, 0, 0, 0)]
    (OUT / f"part_{tag}.csv").write_text("\n".join(txt))
    dii_buy = int(9000 + rng.integers(0, 3000))
    fii_net = int(rng.normal(-800, 1500))
    cash = [
        dict(category="DII", date=D_.strftime("%d-%b-%Y"), buyValue=dii_buy, sellValue=8000, netValue=dii_buy-8000),
        dict(category="FII/FPI", date=D_.strftime("%d-%b-%Y"), buyValue=8000+fii_net, sellValue=8000, netValue=fii_net),
    ]
    (OUT / f"cash_{tag}.json").write_text(json.dumps(cash))
print("Demo data written to", OUT)
