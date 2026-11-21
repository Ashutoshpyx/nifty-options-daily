"""All the calculations. No downloading happens here."""
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

from .config import (CAL_OFFSETS, IC_DELTAS, IC_WINGS, LOT_FALLBACK, RISK_FREE,
                     MIN_TRADED_PAIRS, NEAR_MONEY_PCT, STRIKE_STEP, T, VERT_WIDTH, VIX_BANDS)


# ============================================================ option maths
def _check_cp(cp):
    if cp not in ("CE", "PE"):
        raise ValueError(f"option type must be 'CE' or 'PE', got {cp!r}")


def b76(F, K, Tm, sig, r, cp):
    _check_cp(cp)
    if not (F > 0 and K > 0 and Tm > 0 and sig > 0):
        raise ValueError("F, K, T and sigma must all be positive")
    d1 = (np.log(F / K) + 0.5 * sig ** 2 * Tm) / (sig * np.sqrt(Tm))
    d2 = d1 - sig * np.sqrt(Tm)
    df = np.exp(-r * Tm)
    if cp == "CE":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def implied_vol(price, F, K, Tm, r, cp):
    """Implied vol from a premium. Returns NaN if the price breaks no-arbitrage bounds."""
    _check_cp(cp)
    if not (price == price and price > 0 and F > 0 and K > 0 and Tm > 0):
        return np.nan
    df = np.exp(-r * Tm)
    lower = df * max(F - K, 0) if cp == "CE" else df * max(K - F, 0)
    upper = df * F if cp == "CE" else df * K
    if price <= lower + 0.05 or price >= upper - 1e-9:
        return np.nan
    try:
        return brentq(lambda s_: b76(F, K, Tm, s_, r, cp) - price, 1e-4, 5.0, xtol=1e-9, maxiter=200)
    except Exception:
        return np.nan


def delta(F, K, Tm, sig, r, cp):
    _check_cp(cp)
    if not (sig == sig and sig > 0):
        return np.nan
    d1 = (np.log(F / K) + 0.5 * sig ** 2 * Tm) / (sig * np.sqrt(Tm))
    df = np.exp(-r * Tm)
    return df * norm.cdf(d1) if cp == "CE" else df * (norm.cdf(d1) - 1)


# ============================================================ option chain
def _px(df):
    s = df["SttlmPric"].where(df["SttlmPric"] > 0, df["ClsPric"])
    return s


def build_chain(opts, expiry, trade_date):
    """One row per strike for one expiry, with OI, prices, IV and delta."""
    e = opts[opts["XpryDt"] == expiry]
    ce = e[e["OptnTp"] == "CE"].drop_duplicates("StrkPric").set_index("StrkPric")
    pe = e[e["OptnTp"] == "PE"].drop_duplicates("StrkPric").set_index("StrkPric")
    ch = pd.DataFrame({
        "ce_oi": ce["OpnIntrst"], "ce_doi": ce["ChngInOpnIntrst"],
        "ce_vol": ce["TtlTradgVol"], "ce_px": _px(ce), "ce_prev": ce["PrvsClsgPric"],
        "pe_oi": pe["OpnIntrst"], "pe_doi": pe["ChngInOpnIntrst"],
        "pe_vol": pe["TtlTradgVol"], "pe_px": _px(pe), "pe_prev": pe["PrvsClsgPric"],
    }).sort_index()
    ch[["ce_oi", "ce_doi", "ce_vol", "pe_oi", "pe_doi", "pe_vol"]] = \
        ch[["ce_oi", "ce_doi", "ce_vol", "pe_oi", "pe_doi", "pe_vol"]].fillna(0)

    spot = float(e["UndrlygPric"].median())
    dte = (expiry - pd.Timestamp(trade_date)).days
    if dte < 1:
        raise ValueError(f"{expiry:%d %b %Y} is expired or expires today; not valued")
    Tm = dte / 365.0
    both = ch[(ch.ce_px > 0) & (ch.pe_px > 0)]
    liquid = both[(both.ce_vol > 0) & (both.pe_vol > 0)]          # prefer strikes that actually traded
    pool = liquid[abs(liquid.index / spot - 1) <= NEAR_MONEY_PCT / 100]
    if len(pool) < MIN_TRADED_PAIRS:
        raise ValueError(f"{expiry:%Y-%m-%d}: only {len(pool)} paired traded strikes within {NEAR_MONEY_PCT}% of spot")
    near_k = pool.iloc[np.argsort(np.abs(pool.index.values - spot))[:7]]
    fw = near_k.index.values + (near_k.ce_px.values - near_k.pe_px.values) * np.exp(RISK_FREE * Tm)
    F = float(np.median(fw))
    f_spread = float((fw.max() - fw.min()) / F * 100)               # disagreement between strikes, % of forward

    ch["ce_iv"] = [implied_vol(p, F, k, Tm, RISK_FREE, "CE") for k, p in zip(ch.index, ch.ce_px)]
    ch["pe_iv"] = [implied_vol(p, F, k, Tm, RISK_FREE, "PE") for k, p in zip(ch.index, ch.pe_px)]
    ch["iv"] = np.where(ch.index < F, ch.pe_iv, ch.ce_iv)          # out-of-the-money side IV
    ch["iv"] = ch["iv"].fillna(ch[["ce_iv", "pe_iv"]].mean(axis=1))
    ch["ce_delta"] = [delta(F, k, Tm, s, RISK_FREE, "CE") for k, s in zip(ch.index, ch.iv)]
    ch["pe_delta"] = [delta(F, k, Tm, s, RISK_FREE, "PE") for k, s in zip(ch.index, ch.iv)]
    lots = e["NewBrdLotQty"].dropna().unique()
    if len(lots) != 1 or not (lots[0] > 0) or lots[0] != int(lots[0]):
        raise ValueError(f"invalid or mixed lot size for {expiry:%d %b %Y}: {[float(x) for x in lots]}")
    return ch, dict(spot=spot, F=float(F), dte=dte, Tm=Tm, f_spread_pct=f_spread, traded_pairs=int(len(pool)), lot=int(lots[0]))


def max_pain(ch):
    k = ch.index.values
    pain = [(ch.ce_oi.values * np.maximum(x - k, 0)).sum() +
            (ch.pe_oi.values * np.maximum(k - x, 0)).sum() for x in k]
    return float(k[int(np.argmin(pain))])


def chain_metrics(ch, info, expiry, is_monthly):
    spot, F = info["spot"], info["F"]
    atm = float(ch.index[np.abs(ch.index - spot).argmin()])
    ivs = ch.loc[atm, ["ce_iv", "pe_iv"]].to_numpy(dtype=float)
    if not np.isfinite(ivs).all() or min(ivs) <= 0:
        raise ValueError(f"{expiry:%Y-%m-%d} strike {atm:g}: invalid ATM implied volatility")
    atm_iv = float(ivs.mean())
    straddle = float(ch.loc[atm, "ce_px"] + ch.loc[atm, "pe_px"])
    if ch.ce_oi.sum() <= 0:
        raise ValueError(f"{expiry:%Y-%m-%d}: no outstanding calls to calculate the OI put/call ratio")
    below = ch[ch.index <= spot]
    above = ch[ch.index >= spot]
    support = below.pe_oi.nlargest(3)
    resist = above.ce_oi.nlargest(3)
    p25 = ch[ch.pe_delta.notna() & (ch.index < F)]
    c25 = ch[ch.ce_delta.notna() & (ch.index > F)]
    skew = np.nan
    if len(p25) and len(c25):
        skew = float(p25.loc[(p25.pe_delta.abs() - 0.25).abs().idxmin(), "iv"] -
                     c25.loc[(c25.ce_delta - 0.25).abs().idxmin(), "iv"])
    return dict(
        expiry=expiry, dte=info["dte"], monthly=is_monthly, spot=spot, F=F, atm=atm,
        atm_iv=atm_iv * 100, straddle=straddle,
        sd_move=spot * atm_iv * np.sqrt(info["Tm"]),
        pcr_oi=float(ch.pe_oi.sum() / max(ch.ce_oi.sum(), 1)),
        pcr_vol=float(ch.pe_vol.sum() / max(ch.ce_vol.sum(), 1)),
        max_pain=max_pain(ch), skew=skew * 100 if skew == skew else np.nan,
        support=[(float(k), float(v)) for k, v in support.items()],
        resist=[(float(k), float(v)) for k, v in resist.items()],
        put_wall=float(support.index[0]) if len(support) else np.nan,
        call_wall=float(resist.index[0]) if len(resist) else np.nan,
        fresh_put_writing=[(float(k), float(v)) for k, v in below.pe_doi.nlargest(3).items() if v > 0],
        fresh_call_writing=[(float(k), float(v)) for k, v in above.ce_doi.nlargest(3).items() if v > 0],
        put_unwinding=[(float(k), float(v)) for k, v in below.pe_doi.nsmallest(3).items() if v < 0],
        call_unwinding=[(float(k), float(v)) for k, v in above.ce_doi.nsmallest(3).items() if v < 0],
        net_put_doi=float(below.pe_doi.sum()), net_call_doi=float(above.ce_doi.sum()),
        lot=info["lot"],
    )


def pick_expiries(opts, trade_date, holidays=(), master_expiries=None, master_monthly=None):
    """Near, next, third expiry plus the first monthly after the next weekly."""
    ex = sorted(opts["XpryDt"].unique() if master_expiries is None else master_expiries)
    ex = [pd.Timestamp(x) for x in ex if (pd.Timestamp(x) - pd.Timestamp(trade_date)).days >= 1]
    def monthly_date(e):
        end = e + pd.offsets.MonthEnd(0)
        tuesday = end - pd.Timedelta(days=(end.weekday() - 1) % 7)
        while tuesday.date() in holidays or tuesday.weekday() >= 5:
            tuesday -= pd.Timedelta(days=1)
        return tuesday

    monthly = {e for e in ex if e == monthly_date(e)}
    if master_monthly is not None:
        monthly = set(master_monthly)
    if len(ex) < 3:
        raise ValueError("Need at least 3 future expiries in the bhavcopy")
    near, nxt, third = ex[0], ex[1], ex[2]
    far_m = next((x for x in ex if x in monthly and x > nxt), None)
    if far_m is None:
        raise ValueError("No confirmed far monthly expiry in the contract set")
    required = {near, nxt, third, far_m}
    if not required.issubset(set(pd.to_datetime(opts["XpryDt"]))):
        raise ValueError("Missing option chain for an expiry listed in the contract master")
    return ex, monthly, [near, nxt, third], far_m


# ============================================================ strategy helpers
def condor_candidates(ch, info, m, bias=0):
    F, lot = info["F"], info["lot"]
    oc = ch[(ch.index >= F) & ch.ce_delta.notna()]
    op = ch[(ch.index <= F) & ch.pe_delta.notna()]
    rows = []
    if oc.empty or op.empty:
        return rows
    for d in IC_DELTAS:
        sc = float((oc.ce_delta - d * (0.75 if bias >= 2 else 1)).abs().idxmin())
        sp = float((op.pe_delta.abs() - d * (0.75 if bias <= -2 else 1)).abs().idxmin())
        if not sp < info["spot"] < sc:
            continue
        for w in IC_WINGS:
            lc, lp = sc + w, sp - w
            if lc not in ch.index or lp not in ch.index:
                continue
            px = [ch.loc[sc, "ce_px"], ch.loc[sp, "pe_px"], ch.loc[lc, "ce_px"], ch.loc[lp, "pe_px"]]
            if any(ch.loc[k, col] <= 0 for k, col in ((sc, "ce_vol"), (sp, "pe_vol"), (lc, "ce_vol"), (lp, "pe_vol"))):
                continue
            if not all(p > 0 for p in px):
                continue
            credit = px[0] + px[1] - px[2] - px[3]
            width_c, width_p = lc - sc, sp - lp
            width = max(width_c, width_p)               # worst case: the wider wing breaches
            max_loss = width - credit
            if credit <= 0 or max_loss <= 0 or width_c <= 0 or width_p <= 0:
                continue
            rows.append(dict(
                delta=d, sell_put=sp, buy_put=lp, sell_call=sc, buy_call=lc, wing=width,
                credit=credit, max_loss=max_loss, lot=lot,
                credit_rs=credit * lot, max_loss_rs=max_loss * lot,
                be_low=sp - credit, be_high=sc + credit,
                dist_call_sd=(sc - info["spot"]) / m["sd_move"],
                dist_put_sd=(info["spot"] - sp) / m["sd_move"],
                outside_walls=(sc >= m["call_wall"]) and (sp <= m["put_wall"]),
            ))
    return rows


def vertical(ch, kind, long_k, short_k, lot):
    """Standard verticals only. CE: bull call (long<short, debit) or bear call (long>short, credit).
    PE: bull put (long<short, credit) or bear put (long>short, debit). Anything else returns None."""
    col = "ce_px" if kind == "CE" else "pe_px"
    if kind not in ("CE", "PE") or long_k == short_k or long_k not in ch.index or short_k not in ch.index:
        return None
    volume = kind.lower() + "_vol"
    if volume in ch and min(ch.loc[long_k, volume], ch.loc[short_k, volume]) <= 0:
        return None
    pl, ps = ch.loc[long_k, col], ch.loc[short_k, col]
    if not (pl > 0 and ps > 0):
        return None
    net = ps - pl
    bullish = long_k < short_k
    expect_credit = (not bullish) if kind == "CE" else bullish
    if net == 0 or (net > 0) != expect_credit:
        return None                    # quotes inconsistent with a standard vertical
    width = abs(long_k - short_k)
    if net > 0:
        mp, ml = net, width - net
        be = short_k - net if kind == "PE" else short_k + net
    else:
        mp, ml = width + net, -net
        be = long_k - net if kind == "CE" else long_k + net
    if mp <= 0 or ml <= 0:
        return None
    return dict(kind=kind, long=long_k, short=short_k, net=net, max_profit=mp, max_loss=ml,
                max_profit_rs=mp * lot, max_loss_rs=ml * lot, be=be)


def directional_ideas(ch, m, bias):
    lot, atm = m["lot"], m["atm"]
    ideas = []
    if bias == "bullish":
        ideas.append(("Bull put spread (credit)", vertical(ch, "PE", m["put_wall"] - VERT_WIDTH, m["put_wall"], lot)))
        tgt = m["call_wall"] if m["call_wall"] - atm >= VERT_WIDTH else atm + 2 * VERT_WIDTH
        ideas.append(("Bull call spread (debit)", vertical(ch, "CE", atm, tgt, lot)))
    elif bias == "bearish":
        ideas.append(("Bear call spread (credit)", vertical(ch, "CE", m["call_wall"] + VERT_WIDTH, m["call_wall"], lot)))
        tgt = m["put_wall"] if atm - m["put_wall"] >= VERT_WIDTH else atm - 2 * VERT_WIDTH
        ideas.append(("Bear put spread (debit)", vertical(ch, "PE", atm, tgt, lot)))
    return [(n, v) for n, v in ideas if v]


def calendar_table(near_ch, far_ch, near_info, far_info, atm):
    rows = []
    if near_info["lot"] != far_info["lot"]:
        return rows                      # unequal contract quantities: calendar not valued
    for off in CAL_OFFSETS:
        k = atm + off
        if k not in near_ch.index or k not in far_ch.index:
            continue
        for kind in ("CE", "PE"):
            if (kind == "CE" and off < 0) or (kind == "PE" and off > 0):
                continue  # only out-of-the-money side (plus ATM both)
            col, ivc = ("ce_px", "ce_iv") if kind == "CE" else ("pe_px", "pe_iv")
            vol = kind.lower() + "_vol"
            if min(near_ch.loc[k, vol], far_ch.loc[k, vol]) <= 0:
                continue
            n, f = near_ch.loc[k, col], far_ch.loc[k, col]
            if not (n > 0 and f > 0 and f > n):
                continue          # long calendars only (positive debit)
            intrinsic = max(near_info["F"] - k, 0) if kind == "CE" else max(k - near_info["F"], 0)
            extrinsic = max(n - intrinsic, 0)
            rows.append(dict(strike=k, kind=kind, near_px=n, far_px=f, debit=f - n, near_extrinsic=extrinsic,
                             near_iv=near_ch.loc[k, ivc] * 100, far_iv=far_ch.loc[k, ivc] * 100,
                             iv_gap=(near_ch.loc[k, ivc] - far_ch.loc[k, ivc]) * 100,
                             decay_cover=extrinsic / (f - n) * 100))
    return rows


# ============================================================ futures
def futures_view(futs, trade_date, spot):
    f = futs[futs["XpryDt"] >= pd.Timestamp(trade_date)].sort_values("XpryDt")
    if f.empty:
        return None
    r = f.iloc[0]
    close, prev = float(r["SttlmPric"] if r["SttlmPric"] > 0 else r["ClsPric"]), float(r["PrvsClsgPric"])
    doi = float(r["ChngInOpnIntrst"])
    up, oi_up = close > prev, doi > 0
    label = {(True, True): "Long build-up", (False, True): "Short build-up",
             (True, False): "Short covering", (False, False): "Long unwinding"}[(up, oi_up)]
    if close == prev or doi == 0:
        label = "Neutral"
    dte = max((pd.Timestamp(r["XpryDt"]) - pd.Timestamp(trade_date)).days, 1)
    return dict(expiry=pd.Timestamp(r["XpryDt"]), close=close, prev=prev,
                chg_pct=100 * (close / prev - 1), oi=float(r["OpnIntrst"]), doi=doi,
                doi_pct=100 * doi / max(float(r["OpnIntrst"]) - doi, 1), label=label,
                basis=close - spot, basis_ann=100 * (close / spot - 1) * 365 / dte)


# ============================================================ technicals
def _wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def technicals(h):
    c, hi, lo = h["n_close"], h["n_high"], h["n_low"]
    out = pd.DataFrame(index=h.index)
    for n in (20, 50, 100, 200):
        out[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    d = c.diff()
    ag, al = _wilder(d.clip(lower=0), 14), _wilder((-d).clip(lower=0), 14)
    rsi = 100 - 100 / (1 + ag / al.replace(0, np.nan))
    rsi = rsi.where(~((al == 0) & (ag > 0)), 100.0).where(~((al == 0) & (ag == 0)), 50.0)
    out["rsi"] = rsi
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    out["macd"], out["macd_sig"] = macd, macd.ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_sig"]
    tr = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = _wilder(tr, 14)
    out["atr"] = atr
    up, dn = hi.diff(), -lo.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=h.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=h.index)
    pdi, mdi = 100 * _wilder(pdm, 14) / atr, 100 * _wilder(mdm, 14) / atr
    out["pdi"], out["mdi"] = pdi, mdi
    out["adx"] = _wilder(100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan), 14)
    sma, sd = c.rolling(20).mean(), c.rolling(20).std()
    out["bb_up"], out["bb_lo"], out["bb_mid"] = sma + 2 * sd, sma - 2 * sd, sma
    out["bb_pctb"] = (c - out["bb_lo"]) / (out["bb_up"] - out["bb_lo"])
    out["bb_width"] = 100 * (out["bb_up"] - out["bb_lo"]) / sma
    out["hv10"] = 100 * np.log(c / c.shift()).rolling(10).std() * np.sqrt(252)
    out["hv20"] = 100 * np.log(c / c.shift()).rolling(20).std() * np.sqrt(252)
    return out


def tech_summary(h, t):
    last, prev = h.iloc[-1], h.iloc[-2]
    x = t.iloc[-1]
    c = last.n_close
    H, L, C = last.n_high, last.n_low, last.n_close   # pivots for the NEXT session
    P = (H + L + C) / 3
    piv = dict(P=P, R1=2 * P - L, S1=2 * P - H, R2=P + (H - L), S2=P - (H - L),
               R3=H + 2 * (P - L), S3=L - 2 * (H - P))
    w = h["n_close"].resample("W-FRI").last().dropna()
    w_ema = w.ewm(span=20, adjust=False).mean()
    yr = h.iloc[-252:]
    if x.adx < 18:
        trend = "Range-bound"
    elif c > x.ema20 > x.ema50 and x.adx >= 22:
        trend = "Uptrend"
    elif c < x.ema20 < x.ema50 and x.adx >= 22:
        trend = "Downtrend"
    else:
        trend = "Mixed / changing"
    rng = last.n_high - last.n_low
    return dict(
        close=c, chg=c - prev.n_close, chg_pct=100 * (c / prev.n_close - 1),
        ema20=x.ema20, ema50=x.ema50, ema100=x.ema100, ema200=x.ema200,
        rsi=x.rsi, macd_hist=x.macd_hist, adx=x.adx, pdi=x.pdi, mdi=x.mdi,
        atr=x.atr, atr_pct=100 * x.atr / c, bb_pctb=x.bb_pctb, bb_width=x.bb_width,
        bb_width_pct=float((t["bb_width"].iloc[-252:] <= x.bb_width).mean() * 100),
        hv10=x.hv10, hv20=x.hv20, pivots=piv, trend=trend,
        weekly_above_ema20=bool(w.iloc[-1] > w_ema.iloc[-1]),
        hi20=h.n_high.iloc[-20:].max(), lo20=h.n_low.iloc[-20:].min(),
        hi52=yr.n_high.max(), lo52=yr.n_low.min(),
        range_vs_atr=rng / x.atr if x.atr else np.nan,
        close_pos=(c - last.n_low) / rng if rng else 0.5,
    )


def vix_summary(h, ts):
    v = h["vix"].dropna()
    cur = v.iloc[-1]
    yr = v.iloc[-252:]
    band = next(lbl for lim, lbl in VIX_BANDS if cur < lim)
    return dict(
        vix=cur, chg=cur - v.iloc[-2], chg_pct=100 * (cur / v.iloc[-2] - 1),
        chg5_pct=100 * (cur / v.iloc[-6] - 1) if len(v) > 6 else np.nan,
        pctile=float((yr <= cur).mean() * 100),
        ivrank=float(100 * (cur - yr.min()) / (yr.max() - yr.min())) if yr.max() > yr.min() else np.nan,
        avg20=v.iloc[-20:].mean(), hi=yr.max(), lo=yr.min(), band=band,
        daily_move_pct=cur / np.sqrt(252),
        weekly_move_pct=cur / np.sqrt(52),
    )


# ============================================================ scorecards (structured)
def _it(label, value, rule, ok):
    return dict(label=label, value=value, rule=rule, state=0 if ok is None else (1 if ok else -1))


def event_check(label, events):
    if events is None:
        return _it(label, "Coverage unverified", "0", None)
    return _it(label, "; ".join(events) or "0", "0", len(events) == 0)


def condor_checks(vs, ts, m1, events_before):
    gap, sd = m1["call_wall"] - m1["put_wall"], m1["sd_move"]
    items = [
        _it("VIX percentile 1y", f"{vs['pctile']:.0f}", f">={T['ic_vix_pct_min']}", vs["pctile"] >= T["ic_vix_pct_min"]),
        _it("VIX minus actual vol", f"{vs['vix'] - ts['hv20']:+.1f}", ">=0", vs["vix"] - ts["hv20"] >= 0),
        _it("ADX", f"{ts['adx']:.0f}", f"<{T['ic_adx_max']}", ts["adx"] < T["ic_adx_max"]),
        _it("Wall gap / 1SD", f"{gap:.0f} / {sd:.0f}", f">={T['ic_wall_width_min']:g}x",
            m1["put_wall"] < m1["spot"] < m1["call_wall"] and gap >= T["ic_wall_width_min"] * sd),
        _it("PCR (OI)", f"{m1['pcr_oi']:.2f}", f"{T['ic_pcr_low']}-{T['ic_pcr_high']}", T["ic_pcr_low"] <= m1["pcr_oi"] <= T["ic_pcr_high"]),
        _it("VIX 5d change %", f"{vs['chg5_pct']:+.1f}", f"<{T['ic_vix_5d_rise_max']:.0f}", vs["chg5_pct"] == vs["chg5_pct"] and vs["chg5_pct"] < T["ic_vix_5d_rise_max"]),
        event_check("Events before expiry", events_before),
    ]
    s = sum(1 for i in items if i["state"] == 1)
    return s, len(items), ("FAVOURABLE" if s >= 5 else "SELECTIVE" if s >= 3 else "AVOID"), items


def calendar_checks(vs, ts, m_near, m_far, events_before):
    gap = m_near["atm_iv"] - m_far["atm_iv"]
    pin = abs(m_near["spot"] / m_near["max_pain"] - 1) * 100
    items = [
        _it("VIX percentile 1y", f"{vs['pctile']:.0f}", f"<={T['cal_vix_pct_max']}", vs["pctile"] <= T["cal_vix_pct_max"]),
        _it("Near IV - far IV", f"{gap:+.1f}", f">={T['cal_term_gap_min']:g}", gap >= T["cal_term_gap_min"]),
        _it("ADX", f"{ts['adx']:.0f}", f"<{T['cal_adx_max']}", ts["adx"] < T["cal_adx_max"]),
        _it("Spot vs max pain %", f"{pin:.2f}", f"<={T['cal_pin_pct']}", pin <= T["cal_pin_pct"]),
        event_check("Events before near expiry", events_before),
    ]
    s = sum(1 for i in items if i["state"] == 1)
    return s, len(items), ("FAVOURABLE" if s >= 4 else "SELECTIVE" if s >= 3 else "AVOID"), items


def bias_items(ts, m1, fut, part):
    """Direction signals. A signal with a missing input is left out (not counted as neutral)."""
    it = []
    ok = lambda *xs: all(x == x for x in xs)
    def add(label, value, v): it.append(dict(label=label, value=value, state=v))
    if ok(ts["close"], ts["ema20"]):
        add("Close vs EMA20", f"{ts['close']:.0f} / {ts['ema20']:.0f}", int(np.sign(ts["close"] - ts["ema20"])))
    if ok(ts["ema20"], ts["ema50"]):
        add("EMA20 vs EMA50", f"{ts['ema20']:.0f} / {ts['ema50']:.0f}", int(np.sign(ts["ema20"] - ts["ema50"])))
    if ok(ts["macd_hist"]):
        add("MACD histogram", f"{ts['macd_hist']:+.1f}", int(np.sign(ts["macd_hist"] - 0)))
    if ok(ts["rsi"]):
        add("RSI(14)", f"{ts['rsi']:.0f}", 1 if ts["rsi"] > 55 else (-1 if ts["rsi"] < 45 else 0))
    if fut:
        add("Futures activity", fut["label"], {"Long build-up": 1, "Short covering": 1, "Short build-up": -1, "Long unwinding": -1}.get(fut["label"], 0))
    if ok(m1["pcr_oi"]):
        add("PCR (OI)", f"{m1['pcr_oi']:.2f}", 1 if m1["pcr_oi"] > 1.2 else (-1 if m1["pcr_oi"] < 0.7 else 0))
    pts = sum(i["state"] for i in it)
    return pts, ("bullish" if pts >= T["bias_bull"] else "bearish" if pts <= T["bias_bear"] else "neutral"), it


def calendar_scenarios(near_info, far_info, k, kind, debit, lot, far_iv, moves=(-3, -2, -1, 0, 1, 2, 3), iv_shifts=(0.0, -0.03), short_qty=1):
    """P&L per lot for a long calendar at the NEAR expiry, for spot moves in % and far-IV shifts.
    Assumes the far option is repriced with Black-76 at (far expiry - near expiry) time left,
    the forward carries at the model rate, near leg settles at intrinsic. Costs ignored."""
    t_left = far_info["Tm"] - near_info["Tm"]
    if not (t_left > 0 and far_iv == far_iv and far_iv > 0):
        return []
    rows = []
    for shift in iv_shifts:
        row = []
        for mv in moves:
            S = near_info["spot"] * (1 + mv / 100)
            Ff = S * np.exp(RISK_FREE * t_left)
            far_val = b76(Ff, k, t_left, max(far_iv + shift, 0.01), RISK_FREE, kind)
            near_val = max(S - k, 0) if kind == "CE" else max(k - S, 0)
            row.append((far_val - short_qty * near_val - debit) * lot)
        rows.append((shift * 100, row))
    return rows


def validate_expiries(expiries, holidays):
    """Every expiry we use must be a weekday and not a listed exchange holiday."""
    hol = set(holidays)
    def is_scheduled(expiry):
        expiry = pd.Timestamp(expiry)
        nominal = expiry + pd.Timedelta(days=(1 - expiry.weekday()) % 7)
        while nominal.weekday() >= 5 or nominal.date() in hol:
            nominal -= pd.Timedelta(days=1)
        return nominal == expiry

    bad = [e for e in expiries if not is_scheduled(e)]
    if bad:
        raise ValueError("expiry differs from the holiday-adjusted Tuesday: " + ", ".join(f"{pd.Timestamp(e):%d %b %Y}" for e in bad))
