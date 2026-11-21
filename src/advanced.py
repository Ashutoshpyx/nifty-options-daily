"""Second layer of analysis: things a working options trader looks at beyond the basics."""
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from .analysis import b76, calendar_scenarios
from .config import RISK_FREE, T

# ====================================================================== Greeks
def greeks(F, K, Tm, sig, cp, r=RISK_FREE, spot=None):
    """Per-unit Greeks. vega = change for +1 vol point, theta = change for 1 calendar day.
    Without `spot`, delta/gamma are with respect to the FORWARD. With `spot`, they are with
    respect to the index (dF/dS = F/S, since the forward is spot grown at the carry rate)."""
    if not (sig and sig > 0 and Tm > 0):
        return dict(delta=np.nan, gamma=np.nan, vega=np.nan, theta=np.nan)
    d1 = (np.log(F / K) + 0.5 * sig ** 2 * Tm) / (sig * np.sqrt(Tm))
    df = np.exp(-r * Tm)
    p0 = b76(F, K, Tm, sig, r, cp)
    dF = df * norm.cdf(d1) if cp == "CE" else df * (norm.cdf(d1) - 1)
    gF = df * norm.pdf(d1) / (F * sig * np.sqrt(Tm))
    k = F / spot if spot else 1.0
    return dict(delta=dF * k, gamma=gF * k * k, delta_fwd=dF, gamma_fwd=gF,
                vega=b76(F, K, Tm, sig + 0.01, r, cp) - p0,
                theta=b76(F, K, max(Tm - 1 / 365, 1e-6), sig, r, cp) - p0)


def leg_greeks(ch, info, k, kind):
    col = "ce_iv" if kind == "CE" else "pe_iv"
    sig = ch.loc[k, col]
    if not sig == sig:
        sig = ch.loc[k, "iv"]
    return greeks(info["F"], k, info["Tm"], sig, kind, spot=info["spot"])


def position_greeks(legs, lot):
    """legs = [(chain, info, strike, 'CE'/'PE', +1 buy / -1 sell)] -> totals in rupees per lot."""
    tot = dict(delta=0.0, gamma=0.0, vega=0.0, theta=0.0)
    for ch, info, k, kind, q in legs:
        g = leg_greeks(ch, info, k, kind)
        for key in tot:
            tot[key] += q * g[key] * (1 if key in ("delta", "gamma") else 1)
    return dict(delta=tot["delta"] * lot, gamma=tot["gamma"] * lot, vega=tot["vega"] * lot, theta=tot["theta"] * lot)


# ====================================================================== history-based stats
def load_calendar():
    """Returns (holiday dates, years whose list has been verified). Raises ValueError if unreadable."""
    import json
    base = Path(__file__).resolve().parent.parent / "data"
    try:
        hol = [d.date() for d in pd.to_datetime(pd.read_csv(base / "holidays.csv")["date"]).dropna()]
        with open(base / "holiday_coverage.json") as fh:
            years = {int(y) for y in json.load(fh)["years"]}
    except Exception as err:
        raise ValueError(f"holiday calendar files unreadable ({err}); fix data/holidays.csv and data/holiday_coverage.json")
    return hol, years


def load_holidays():
    return load_calendar()[0]


def trading_days_to(day, expiry, holidays=None):
    hol = load_holidays() if holidays is None else holidays
    return max(int(np.busday_count((pd.Timestamp(day) + pd.Timedelta(days=1)).date(),
                                   (pd.Timestamp(expiry) + pd.Timedelta(days=1)).date(), holidays=hol)), 1)


def window_stats(hist, n, lookback=750):
    h = hist.dropna(subset=["n_high", "n_low", "n_close"]).iloc[-lookback:]   # keep VIX gaps as NaN so sessions are not squeezed together
    c, hi, lo, v = h.n_close.values, h.n_high.values, h.n_low.values, h.vix.values
    N = len(c) - n
    if N < 50:
        return None
    up = np.array([hi[i + 1:i + n + 1].max() / c[i] - 1 for i in range(N)])
    dn = np.array([1 - lo[i + 1:i + n + 1].min() / c[i] for i in range(N)])
    end = np.array([c[i + n] / c[i] - 1 for i in range(N)])
    return dict(up=up, dn=dn, end=end, vix=v[:N], n=n)


def excursion_table(w, spot):
    rows = []
    for q in (50, 80, 90, 95):
        u, d = np.percentile(w["up"], q) * spot, np.percentile(w["dn"], q) * spot
        rows.append((q, u, d))
    return rows


def band_touch(w, pct):
    """Share of past windows where the high or low reached +/-pct, and where the close ended outside."""
    if not np.isfinite(pct) or pct <= 0:
        return np.nan, np.nan
    touch = float(np.mean((w["up"] >= pct) | (w["dn"] >= pct)) * 100)
    outside = float(np.mean(np.abs(w["end"]) >= pct) * 100)
    return touch, outside


def wilson(p, n, z=1.96):
    """95% range for a share p measured on n independent samples."""
    if n <= 0:
        return np.nan, np.nan
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(c - h, 0.0), min(c + h, 1.0)


def condor_history(w, spot, sp, sc, be_low, be_high, cur_vix, n_eff=None):
    """How the same strikes would have fared in past windows (all, and when VIX was similar)."""
    up_need, dn_need = sc / spot - 1, 1 - sp / spot
    touch = (w["up"] >= up_need) | (w["dn"] >= dn_need)
    lose = (w["end"] >= be_high / spot - 1) | (w["end"] <= be_low / spot - 1)
    sim = (w["vix"] >= 0.8 * cur_vix) & (w["vix"] <= 1.2 * cur_vix)
    out = dict(touch_all=touch.mean() * 100, lose_all=lose.mean() * 100, n_all=len(touch))
    lo, hi = wilson(float(lose.mean()), n_eff or len(lose))
    out.update(lose_lo=lo * 100, lose_hi=hi * 100, n_eff=n_eff or len(lose))
    if sim.sum() >= 30:
        out.update(touch_sim=touch[sim].mean() * 100, lose_sim=lose[sim].mean() * 100, n_sim=int(sim.sum()))
    return out


def vix_conditional(hist, cur_pct, horizon=5):
    v = hist["vix"].dropna()
    if len(v) < 400:
        return None
    pct = v.rolling(252).apply(lambda x: (x <= x[-1]).mean() * 100, raw=True)
    fwd = v.shift(-horizon) / v - 1
    nc = hist["n_close"].reindex(v.index)
    fwd_n = (nc.shift(-horizon) / nc - 1).abs()
    m = ((pct - cur_pct).abs() <= 15) & fwd.notna()
    if m.sum() < 20:
        return None
    return dict(n=int(m.sum()), mean_chg=float(fwd[m].mean() * 100), up_share=float((fwd[m] > 0).mean() * 100),
                avg_abs_nifty=float(fwd_n[m].mean() * 100), horizon=horizon)


def vrp_percentile(hist):
    """Volatility risk premium = VIX minus actual 20-day movement, ranked against last year."""
    c = hist["n_close"]
    hv = 100 * np.log(c / c.shift()).rolling(20).std() * np.sqrt(252)
    vrp = (hist["vix"] - hv).dropna()
    if len(vrp) < 60:
        return np.nan, np.nan
    yr = vrp.iloc[-252:]
    return float(vrp.iloc[-1]), float((yr <= vrp.iloc[-1]).mean() * 100)


def vix_nifty_divergence(hist, days=5):
    if len(hist) <= days + 1 or hist["vix"].iloc[-days - 1:].isna().any():
        return np.nan, np.nan, "Not enough aligned history for a Nifty/VIX comparison."
    c, v = hist["n_close"], hist["vix"]
    dn = 100 * (c.iloc[-1] / c.iloc[-days - 1] - 1)
    dv = 100 * (v.iloc[-1] / v.iloc[-days - 1] - 1)
    if dn < -0.5 and dv < -3:
        msg = "Nifty fell but VIX also fell: market is calm about the dip (can be complacent)."
    elif dn > 0.5 and dv > 3:
        msg = "Nifty rose but VIX also rose: rally is nervous; hedging demand is rising."
    elif dn < -0.5 and dv > 3:
        msg = "Nifty down, VIX up: normal fear move."
    elif dn > 0.5 and dv < -3:
        msg = "Nifty up, VIX down: healthy, comfortable uptrend."
    else:
        msg = "No clear divergence between Nifty and VIX."
    return dn, dv, msg


# ====================================================================== levels
def confluence(levels, spot, width=40):
    if width < 0:
        raise ValueError("width must be zero or positive")
    if not levels:
        return []
    items = sorted(levels.items(), key=lambda kv: kv[1])
    clusters, cur = [], [items[0]]
    for it in items[1:]:
        if it[1] - cur[0][1] <= width:           # whole cluster must fit inside `width`, not just neighbours
            cur.append(it)
        else:
            clusters.append(cur); cur = [it]
    clusters.append(cur)
    out = []
    for c in clusters:
        if len(c) >= 2:
            lvl = float(np.mean([x[1] for x in c]))
            out.append(dict(level=lvl, names=[x[0] for x in c], n=len(c),
                            side="support" if lvl < spot else "resistance"))
    return sorted(out, key=lambda d: abs(d["level"] - spot))[:8]


# ====================================================================== option activity
CE_LABEL = {(True, True): ("Call buying", "bullish"), (False, True): ("Call writing", "bearish"),
            (True, False): ("Call short covering", "bullish"), (False, False): ("Call long unwinding", "bearish")}
PE_LABEL = {(True, True): ("Put buying", "bearish"), (False, True): ("Put writing", "bullish"),
            (True, False): ("Put short covering", "bearish"), (False, False): ("Put long unwinding", "bullish")}


def buildup_table(ch, spot, top=8):
    sub = ch[(ch.index >= spot * 0.95) & (ch.index <= spot * 1.05)]
    rows = []
    for k, r in sub.iterrows():
        for kind, doi, px, pv, oi in (("CE", r.ce_doi, r.ce_px, r.ce_prev, r.ce_oi), ("PE", r.pe_doi, r.pe_px, r.pe_prev, r.pe_oi)):
            if not doi or not (px > 0) or pv != pv or px == pv:
                continue
            lab, view = (CE_LABEL if kind == "CE" else PE_LABEL)[(px >= pv, doi > 0)]
            rows.append(dict(strike=k, kind=kind, doi=doi, oi=oi, px=px, dpx=px - pv, label=lab, view=view))
    if not rows:
        return [], dict(bull=np.nan, bear=np.nan)
    df = pd.DataFrame(rows)
    bull = df.loc[df.view == "bullish", "doi"].abs().sum()
    bear = df.loc[df.view == "bearish", "doi"].abs().sum()
    share = dict(bull=100 * bull / (bull + bear) if bull + bear else np.nan,
                 bear=100 * bear / (bull + bear) if bull + bear else np.nan)
    top_rows = df.reindex(df.doi.abs().sort_values(ascending=False).index).head(top).to_dict("records")
    return top_rows, share


def pin_strikes(ch, info, top=3):
    sub = ch[(ch.index >= info["spot"] * 0.97) & (ch.index <= info["spot"] * 1.03)].copy()
    sig = sub["iv"].where(sub["iv"] > 0)
    d1 = (np.log(info["F"] / sub.index.values) + 0.5 * sig ** 2 * info["Tm"]) / (sig * np.sqrt(info["Tm"]))
    gamma = np.exp(-RISK_FREE * info["Tm"]) * norm.pdf(d1) / (info["F"] * sig * np.sqrt(info["Tm"]))
    sub["pin"] = gamma * (sub.ce_oi + sub.pe_oi)
    sub = sub.dropna(subset=["pin"])
    return [float(k) for k in sub["pin"].nlargest(top).index]


def pcr_family(ch, spot):
    near = ch[(ch.index >= spot * 0.95) & (ch.index <= spot * 1.05)]
    d_ce, d_pe = ch.ce_doi.sum(), ch.pe_doi.sum()
    return dict(
        pcr_oi=ch.pe_oi.sum() / max(ch.ce_oi.sum(), 1),
        pcr_vol=ch.pe_vol.sum() / max(ch.ce_vol.sum(), 1),
        pcr_near=near.pe_oi.sum() / near.ce_oi.sum() if near.ce_oi.sum() > 0 else np.nan,
        pcr_change=(d_pe / d_ce) if d_ce > 0 and d_pe > 0 else np.nan,
    )


def oi_build_since(opts_now, opts_then, expiry, spot, top=4):
    """Strike-wise OI added since an older snapshot, same expiry."""
    def by_strike(o):
        e = o[o["XpryDt"] == expiry]
        return (e[e.OptnTp == "CE"].set_index("StrkPric")["OpnIntrst"],
                e[e.OptnTp == "PE"].set_index("StrkPric")["OpnIntrst"])
    cn, pn = by_strike(opts_now)
    co, po = by_strike(opts_then)
    if co.empty or po.empty:
        return None
    # Older disk snapshots were clipped; their omitted strikes have unknown OI.
    missing = 0 if opts_then.attrs.get("full_coverage", True) else np.nan
    dc = cn - co.reindex(cn.index, fill_value=missing)
    dp = pn - po.reindex(pn.index, fill_value=missing)
    dc, dp = dc[dc.index >= spot], dp[dp.index <= spot]
    return dict(calls_added=[(float(k), float(v)) for k, v in dc.nlargest(top).items() if v > 0],
                puts_added=[(float(k), float(v)) for k, v in dp.nlargest(top).items() if v > 0],
                calls_cut=[(float(k), float(v)) for k, v in dc.nsmallest(top).items() if v < 0],
                puts_cut=[(float(k), float(v)) for k, v in dp.nsmallest(top).items() if v < 0])


# ====================================================================== FII / DII
def participant_view(part, prev):
    """Add options bias and day-on-day changes. prev is the previous day's row (dict) or None."""
    if not part or "FII" not in part:
        return None
    f = part["FII"]
    opt_bias = (f["call_long"] - f["call_short"]) - (f["put_long"] - f["put_short"])
    out = dict(fut_net=f["fut_net"], fut_long_pct=f["fut_long_pct"], opt_bias=opt_bias,
               call_net=f["call_long"] - f["call_short"], put_net=f["put_long"] - f["put_short"])
    if prev:
        out["d_fut_net"] = f["fut_net"] - prev.get("FII_fut_net", np.nan)
        out["d_opt_bias"] = opt_bias - prev.get("FII_opt_bias", np.nan)
        out["d_long_pct"] = f["fut_long_pct"] - prev.get("FII_fut_long_pct", np.nan)
    return out


def smart_money_score(pv, cash_total):
    it = []
    def add(label, value, v): it.append(dict(label=label, value=value, state=v))
    if pv:
        p = pv["fut_long_pct"]
        add("FII % long, index futures", f"{p:.0f}", 1 if p > 55 else (-1 if p < 45 else 0))
        if "d_fut_net" in pv and pv["d_fut_net"] == pv["d_fut_net"]:
            add("FII net futures change", f"{pv['d_fut_net']:+,.0f}", 1 if pv["d_fut_net"] > 0 else (-1 if pv["d_fut_net"] < 0 else 0))
        add("FII options bias (calls-puts)", f"{pv['opt_bias']:+,.0f}", 1 if pv["opt_bias"] > 0 else (-1 if pv["opt_bias"] < 0 else 0))
    if cash_total is not None and np.isfinite(cash_total):
        s5 = cash_total
        add("FII cash 5d net (Rs cr)", f"{s5:+,.0f}", 1 if s5 > 0 else (-1 if s5 < 0 else 0))
    pts = sum(i["state"] for i in it)
    return pts, ("bullish" if pts >= 2 else "bearish" if pts <= -2 else "mixed"), it


# ====================================================================== sizing / rules
def lots_for_risk(max_loss_rs, capital, risk_pct):
    if max_loss_rs <= 0:
        return 0
    return int((capital * risk_pct / 100) // max_loss_rs)

def double_calendars(near, far, front, back, pairs):
    """Two near lots short and one next-expiry lot long per side. Each side retains its own implied volatility."""
    lot = front["lot"]
    if lot != back["lot"]:
        return []
    rows = []
    for put, call in pairs:
        legs = []
        scenarios = []
        sold = bought = 0.0
        for strike, kind in [(put, "PE"), (call, "CE")]:
            if strike not in near.index or strike not in far.index:
                break
            price, vol, iv = [kind.lower() + suffix for suffix in ("_px", "_vol", "_iv")]
            values = [chain.at[strike, col] for chain in (near, far) for col in (price, vol, iv)]
            if not all(np.isfinite(x) and x > 0 for x in values):
                break
            n, f = near.at[strike, price], far.at[strike, price]
            sold += 2*n
            bought += f
            legs.extend([(near, front, strike, kind, -2), (far, back, strike, kind, 1)])
            scenarios.append(calendar_scenarios(front, back, strike, kind, f-2*n, lot,
                             far.at[strike, iv], iv_shifts=(-.03, 0., .03), short_qty=2))
        if len(legs) == 4 and all(scenarios):
            combined = [(shift, np.add(put, call)) for (shift, put), (_, call)
                        in zip(*scenarios)]
            rows.append(dict(put=put, call=call, sold=sold, bought=bought,
                             debit=(bought-sold)*lot, g=position_greeks(legs, lot), scenarios=combined))
    return rows
