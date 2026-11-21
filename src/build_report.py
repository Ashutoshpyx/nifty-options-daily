"""Run:  python -m src.build_report
Options for testing without NSE:
  --bhav-file FILE   local UDiFF-style F&O bhavcopy csv instead of downloading
  --hist-file FILE   local price history csv instead of Yahoo
  --part-file FILE   local participant-wise OI csv
  --cash-file FILE   local FII/DII cash json
  --date YYYY-MM-DD  build for this trade date (default: latest available)
  --force            rebuild even if the report exists
Output: docs/index.html (latest), docs/YYYY-MM-DD.html, reports/latest.md (short text brief)
"""
import argparse
import hashlib
import datetime as dt
import json
import sys
from pathlib import Path
from filelock import FileLock

import numpy as np
import pandas as pd

from . import decision
from . import advanced as X
from . import analysis as A
from . import data as D
from . import notify
from . import render as R
from .config import (ADJUST_ATR_MULT, CAPITAL, FUT_TOL_HARD, FUT_TOL_WARN, LOT_FALLBACK, MIN_TRADED_PAIRS, PROFIT_TARGET,
                     QUALITY_F_SPREAD_HARD, RISK_PCT, SHOW_PLAN, SPOT_TOL_HARD, SPOT_TOL_WARN, STOP_MULT, STRICT_CALENDAR)

nan = np.nan


def build(args):
    local = any((args.bhav_file, args.hist_file, args.cash_file, args.part_file, args.contract_file))
    mode = "synthetic" if args.demo else "replay" if local else "exchange"
    if args.demo and not all((args.bhav_file, args.hist_file, args.part_file, args.cash_file)):
        raise ValueError("Demo mode requires all four local inputs")
    D.configure_storage(mode)
    with FileLock(str(D.DATA / "build.lock"), timeout=300):
        return build_locked(args, mode)


def build_locked(args, mode):
    sess = None if mode == "synthetic" else D.nse_session()
    warnings = []
    if args.bhav_file:
        raw = pd.read_csv(args.bhav_file)
        day = pd.to_datetime(raw["TradDt"].iloc[0]).date()
    else:
        start = dt.date.fromisoformat(args.date) if args.date else None
        if start:
            day, raw = start, D.fetch_fo_bhavcopy(start, sess)
        else:
            day, raw = D.find_latest_bhavcopy(sess)
        if raw is None:
            sys.exit("Could not download the NSE F&O bhavcopy (NSE may be blocking this server or the file "
                     "is not out yet). Try later, or run from your own PC.")
    out_md = D.ROOT / "docs" / f"{day:%Y-%m-%d}.html"
    if args.date and dt.date.fromisoformat(args.date) != day:
        raise ValueError(f"Requested {args.date}, input file is dated {day}")
    completed = D.DATA / f"{day}.complete"
    dated_brief = D.ROOT / "reports" / f"{day}.md"
    def fingerprints():
        return {"source": mode, "html": hashlib.sha256(out_md.read_bytes()).hexdigest(),
                "brief": hashlib.sha256(dated_brief.read_bytes()).hexdigest()}

    if (mode == "exchange" and not args.force and completed.exists() and out_md.exists()
            and dated_brief.exists() and completed.read_text() == json.dumps(fingerprints())):
        # Repair missing or replaced latest copies from the verified dated outputs.
        if out_md == max(out_md.parent.glob("????-??-??.html")):
            for dated, latest in [(out_md, out_md.with_name("index.html")),
                                  (dated_brief, dated_brief.with_name("latest.md"))]:
                content = dated.read_bytes()
                if not latest.exists() or latest.read_bytes() != content:
                    D.atomic_write(latest, lambda path: path.write_bytes(content))
        print("Report already exists for", day)
        return
    if mode != "exchange":
        warnings.append("SYNTHETIC DEMO | INVENTED DATA" if mode == "synthetic" else "LOCAL INPUT REPLAY | independently verify data provenance.")
    ds = f"{day:%Y-%m-%d}"

    try:
        opts, futs = D.prepare_nifty(raw)
    except ValueError as err:
        sys.exit(f"Data check failed: {err}")
    if opts.empty:
        sys.exit("No NIFTY option rows found - NSE column names may have changed.")
    if pd.Timestamp(day) != opts["TradDt"].iloc[0]:
        sys.exit(f"File trade date {opts['TradDt'].iloc[0]:%d %b %Y} does not match requested {day:%d %b %Y}.")
    # The EOD master can retire contracts that settled in this bhavcopy.
    # Use only outstanding contracts for every forward-looking panel and aggregate.
    opts = opts[opts.XpryDt > pd.Timestamp(day)]
    futs = futs[futs.XpryDt > pd.Timestamp(day)]
    if opts.empty or futs.empty:
        raise ValueError("No outstanding NIFTY option or futures contracts")
    try:
        hol, covered = X.load_calendar()
    except ValueError as err:
        sys.exit(str(err))
    if STRICT_CALENDAR and day.year not in covered:
        sys.exit(f"Holiday list for {day.year} is not verified in data/holiday_coverage.json. Add the official NSE list for {day.year} to data/holidays.csv, then add the year to the coverage file.")
    now_ist = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    age_days = (now_ist.date() - day).days
    if age_days > 3:
        warnings.append(f"Latest available session is {age_days} days old; the newest NSE file may not be published or reachable.")
    full_history = D.update_history(day, sess, float(opts["UndrlygPric"].median()), warnings, args.hist_file)
    hist = full_history.loc[:pd.Timestamp(day)]
    spot_gap = abs(float(opts["UndrlygPric"].median()) / float(hist.loc[pd.Timestamp(day), "n_close"]) - 1) * 100 if pd.Timestamp(day) in hist.index else 0.0
    if spot_gap > SPOT_TOL_HARD:
        sys.exit(f"Nifty mark in the option file differs from the index close by {spot_gap:.2f}% (limit {SPOT_TOL_HARD}%). No report produced.")
    if spot_gap > SPOT_TOL_WARN:
        warnings.append(f"Nifty mark in the option file differs from the index close by {spot_gap:.2f}%.")
    last_ts = pd.Timestamp(day)
    if hist.index[-1] != last_ts or pd.isna(hist.loc[last_ts, "vix"]):
        sys.exit(f"India VIX is missing for {day:%d %b %Y}; refusing to mix today's Nifty with an older VIX. Try again later.")
    tech = A.technicals(hist)
    ts, vs = A.tech_summary(hist, tech), A.vix_summary(hist, pd.Timestamp(day))

    # ---- expiries and chains
    master_dates = master_monthly = None
    if mode != "synthetic":
        master = D.load_master(day, sess, args.contract_file)
        master_dates, master_monthly = D.verify_master(master, opts, futs)
    exp_all, monthly, (e1, e2, e3), far_m = A.pick_expiries(opts, day, hol, master_dates, master_monthly)
    horizon_years = set(range(day.year, max(e3, far_m).year + 1))
    if not horizon_years.issubset(covered):
        if STRICT_CALENDAR:
            raise ValueError("Unverified holiday coverage within selected expiry horizon")
        warnings.append("Holiday coverage unverified for part of the expiry horizon.")
    chains, mets, infos = {}, {}, {}
    for e in [e1, e2, e3] + ([far_m] if far_m and far_m not in (e1, e2, e3) else []):
        chains[e], infos[e] = A.build_chain(opts, e, day)
        mets[e] = A.chain_metrics(chains[e], infos[e], e, e in monthly)
    m1, m2, ch1, in1 = mets[e1], mets[e2], chains[e1], infos[e1]
    far_e = far_m or e3
    spot = m1["spot"]
    used = list(dict.fromkeys([e1, e2, e3, far_e]))
    try:
        A.validate_expiries(used, hol)
    except ValueError as err:
        sys.exit(f"Contract check failed: {err}")
    for e in used:
        if infos[e]["f_spread_pct"] > QUALITY_F_SPREAD_HARD or infos[e]["traded_pairs"] < MIN_TRADED_PAIRS:
            sys.exit(f"Chain quality check failed for {e:%d %b}: put-call forwards disagree by {infos[e]['f_spread_pct']:.2f}% "
                     f"and {infos[e]['traded_pairs']} near-money strike pairs traded (need at least {MIN_TRADED_PAIRS}). No report produced.")
    if m1["lot"] != LOT_FALLBACK:
        warnings.append(f"Lot size in the NSE file ({m1['lot']}) differs from config.py ({LOT_FALLBACK}); the file value is used.")
    for e in used[1:]:
        if infos[e]["lot"] != m1["lot"]:
            warnings.append(f"{e:%d %b} has lot {infos[e]['lot']} vs {m1['lot']} for {e1:%d %b}; calendars across them are not shown.")
    for e in (e1, e2, e3):
        if infos[e]["f_spread_pct"] > 0.15:
            warnings.append(f"{e:%d %b}: put-call forwards disagree by {infos[e]['f_spread_pct']:.2f}% (stale or thin prices); IV and Greeks less reliable.")
    fut = A.futures_view(futs, day, spot)
    if fut and fut["expiry"] in infos:
        gap = abs(fut["close"] / infos[fut["expiry"]]["F"] - 1) * 100
        if gap > FUT_TOL_HARD:
            sys.exit(f"Nifty future and option-implied forward differ by {gap:.2f}% for {fut['expiry']:%d %b} (limit {FUT_TOL_HARD}%). Futures or option prices look wrong; no report produced.")
    if fut and fut["expiry"] in infos and abs(fut["close"] / infos[fut["expiry"]]["F"] - 1) * 100 > FUT_TOL_WARN:
        warnings.append(f"Option-implied forward differs from the Nifty future by {100 * (fut['close'] / infos[fut['expiry']]['F'] - 1):+.2f}% for {fut['expiry']:%d %b}.")



    # ---- FII / DII
    if args.part_file:
        part = D.summarise_participants(D.parse_participant_text(Path(args.part_file).read_text(), day))
    else:
        part = D.summarise_participants(D.fetch_participant_oi(day, sess))
    plog = D.load_participants_log()
    pprev = plog[plog.index < ds].iloc[-1].to_dict() if len(plog[plog.index < ds]) else None
    pv = X.participant_view(part, pprev)
    cash = D.parse_cash_rows(json.loads(Path(args.cash_file).read_text())) if args.cash_file else D.fetch_fii_dii_cash(sess)
    if cash and cash["FII"]["date"].date() != day:
        warnings.append(f"FII/DII cash numbers are dated {cash['FII']['date']:%d %b}, not {day:%d %b}.")
        cash = None
    all_cash = D.merged_cash(cash)
    clog = all_cash.loc[:ds]
    if not pv:
        warnings.append("FII/DII participant OI not available today.")
    if clog.empty:
        warnings.append("FII/DII cash flow not available (history builds from the first successful run).")
    cash_totals = {n: D.cash_window(clog, day, n, hol, hist.index) for n in (5, 20)}
    sm_pts, sm_bias, sm_items = X.smart_money_score(pv, cash_totals[5])

    # ---- weekly-expiry statistics from price history
    n_sess = X.trading_days_to(day, e1, hol)
    w = X.window_stats(hist, n_sess)
    sd_pct = m1["sd_move"] / spot
    touch, outside = X.band_touch(w, sd_pct) if w else (nan, nan)
    hist_1sd = float(np.percentile(np.abs(w["end"]), 68)) if w else nan
    rich = sd_pct / hist_1sd if hist_1sd == hist_1sd and hist_1sd > 0 else nan
    gc, gp = X.leg_greeks(ch1, in1, m1["atm"], "CE"), X.leg_greeks(ch1, in1, m1["atm"], "PE")
    straddle_theta = -(gc["theta"] + gp["theta"])            # points the straddle loses per day

    # ---- VIX extras
    vcond = X.vix_conditional(hist, vs["pctile"])
    vrp, vrp_pct = X.vrp_percentile(hist)
    d_n, d_v, div_msg = X.vix_nifty_divergence(hist)

    # ---- OI extras
    pf = {e: X.pcr_family(chains[e], mets[e]["spot"]) for e in (e1, e2, e3)}
    tot_pcr = opts.loc[opts.OptnTp == "PE", "OpnIntrst"].sum() / max(opts.loc[opts.OptnTp == "CE", "OpnIntrst"].sum(), 1)
    bu_rows, bu_share = X.buildup_table(ch1, spot)
    pins = X.pin_strikes(ch1, in1)
    old, old_date = D.load_old_snapshot(day, 3)
    build3 = X.oi_build_since(opts, old, e1, spot) if old is not None else None

    # ---- levels
    pv_l = ts["pivots"]
    lv = {"Pivot S2": pv_l["S2"], "Pivot S1": pv_l["S1"], "Pivot": pv_l["P"], "Pivot R1": pv_l["R1"], "Pivot R2": pv_l["R2"],
          "EMA20": ts["ema20"], "EMA50": ts["ema50"], "EMA100": ts["ema100"], "EMA200": ts["ema200"],
          "Max pain": m1["max_pain"], "20d high": ts["hi20"], "20d low": ts["lo20"]}
    for i, (k, _) in enumerate(m1["support"][:2]): lv[f"Put OI wall {i + 1}"] = k
    for i, (k, _) in enumerate(m1["resist"][:2]): lv[f"Call OI wall {i + 1}"] = k
    zones = X.confluence(lv, spot)

    # ---- scorecards
    ev = D.load_events()

    def events_until(d):
        if not D.event_coverage(ev, day, d):
            return None
        if ev.empty:
            return []
        e = ev[(ev.date > pd.Timestamp(day)) & (ev.date <= d)]
        return [f"{r.date:%d %b} {r.event}" for r in e.itertuples()]
    ic = A.condor_checks(vs, ts, m1, events_until(e1))
    cal = A.calendar_checks(vs, ts, m1, m2, events_until(e1))
    b_pts, bias, b_items = A.bias_items(ts, m1, fut, part)
    total = b_pts + sm_pts
    if len(b_items) < 4:
        warnings.append("Fewer than 4 direction inputs available; direction score suppressed.")
    outlook = ("Insufficient data" if len(b_items) < 4 else "Bullish" if total >= 4 else "Mildly bullish" if total >= 2 else "Bearish" if total <= -4
               else "Mildly bearish" if total <= -2 else "Neutral / range")

    # ---- iron condor desk
    cands = A.condor_candidates(ch1, in1, m1, total if outlook != "Insufficient data" else 0)
    for r in cands:
        legs = [(ch1, in1, r["buy_put"], "PE", +1), (ch1, in1, r["sell_put"], "PE", -1),
                (ch1, in1, r["sell_call"], "CE", -1), (ch1, in1, r["buy_call"], "CE", +1)]
        r["g"] = X.position_greeks(legs, m1["lot"])
        r["hist"] = X.condor_history(w, spot, r["sell_put"], r["sell_call"], r["be_low"], r["be_high"], vs["vix"], n_eff=max(len(w["end"]) // n_sess, 1)) if w else {}
        r["lots"] = X.lots_for_risk(r["max_loss_rs"], CAPITAL, RISK_PCT) if SHOW_PLAN else None
    def touch_rate(row):
        history = row["hist"]
        return history.get("touch_sim", history.get("touch_all", float("inf")))

    cands.sort(key=lambda r: (touch_rate(r), r["hist"].get("lose_sim", r["hist"].get("lose_all", 100)),
                              r["max_loss_rs"]))
    best = cands[0] if SHOW_PLAN and w and cands else None

    # ---- what changed
    log = D.load_metrics_log()
    prev = log[log.index < ds].iloc[-1] if len(log[log.index < ds]) else None
    changes = []
    if prev is not None:
        g = lambda k: prev[k] if k in prev and pd.notna(prev[k]) else None
        changes.append(f"Nifty {ts['close']:,.0f} ({ts['chg_pct']:+.2f}% on the day)")
        if g("vix"): changes.append(f"VIX {vs['vix']:.2f} vs {g('vix'):.2f} at the last report ({vs['vix'] - g('vix'):+.2f})")
        if g("pcr_oi"): changes.append(f"PCR {m1['pcr_oi']:.2f} vs {g('pcr_oi'):.2f}")
        if g("put_wall") and (g("put_wall") != m1["put_wall"] or g("call_wall") != m1["call_wall"]):
            changes.append(f"OI walls moved: put {g('put_wall'):.0f} → {m1['put_wall']:.0f}, call {g('call_wall'):.0f} → {m1['call_wall']:.0f}")
        if g("max_pain") and g("max_pain") != m1["max_pain"]:
            changes.append(f"Max pain {g('max_pain'):.0f} → {m1['max_pain']:.0f}")
        if g("bias_score") is not None and g("bias_score") != b_pts:
            changes.append(f"Technical/OI direction score {g('bias_score'):+.0f} → {b_pts:+d}")
    else:
        changes.append("First report - day-on-day changes appear from the next run.")

    # ---- price ladder
    lk = lambda v: f"{v / 1e5:.1f}"
    ladder = []
    for k, v in m1["resist"]: ladder.append((k, f"Call OI wall {lk(v)}L", "res"))
    for k, v in m1["support"]: ladder.append((k, f"Put OI wall {lk(v)}L", "sup"))
    for nm in ("R2", "R1", "P", "S1", "S2"): ladder.append((pv_l[nm], "Pivot " + ("PP" if nm == "P" else nm), "tech"))
    for nm in ("ema20", "ema50", "ema200"): ladder.append((ts[nm], nm.upper(), "tech"))
    ladder += [(ts["hi20"], "20d high", "tech"), (ts["lo20"], "20d low", "tech"),
               (spot + m1["sd_move"], "1 SD up (options)", "band"), (spot - m1["sd_move"], "1 SD down (options)", "band"),
               (m1["max_pain"], "Max pain", "mp")]
    ladder += [(p, "Gamma-OI strike", "pin") for p in pins]
    exc = X.excursion_table(w, spot) if w else []
    if exc:
        _, u90, d90 = exc[2]
        ladder += [(spot + u90, "90% history up", "hist"), (spot - d90, "90% history down", "hist")]
    if best:
        ladder += [(best["sell_call"], "Screen candidate short call", "trade"), (best["sell_put"], "Screen candidate short put", "trade")]

    upcoming = [f"{r.date:%d %b}  {r.event}  {'' if pd.isna(r.impact) else r.impact}" for r in ev[ev.date > pd.Timestamp(day)].head(6).itertuples()] if not ev.empty and D.event_coverage(ev, day, e1) else []

    all_metrics = D.merged_metrics(day, dict(
        spot=round(spot, 1), vix=round(vs["vix"], 2), vix_pctile=round(vs["pctile"], 1), pcr_oi=round(m1["pcr_oi"], 3),
        max_pain=m1["max_pain"], put_wall=m1["put_wall"], call_wall=m1["call_wall"], atm_iv_e1=round(m1["atm_iv"], 2),
        atm_iv_e2=round(m2["atm_iv"], 2), adx=round(ts["adx"], 1), rsi=round(ts["rsi"], 1), ic_score=ic[0], cal_score=cal[0],
        bias_score=b_pts, smart_score=sm_pts,
        fii_fut_long_pct=round(part["FII"]["fut_long_pct"], 1) if part and "FII" in part else nan))
    log8 = all_metrics.loc[:ds].tail(8)

    trade_review = decision.review(ch1, chains[e2], in1, infos[e2], m1, vs, ts, outlook, w, X.window_stats(hist, 5), events_until(e1))
    if age_days > 3:
        trade_review["reasons"].append("Report is more than three calendar days old.")
    ctx = dict(trade_review=trade_review,
        cash_totals=cash_totals, day=day, ts=ts, vs=vs, m1=m1, pv=pv, part=part, fut=fut, clog=clog, warnings=warnings, changes=changes,
        e1=e1, exps=[e1, e2, e3], mets=mets, chains=chains, ch1=ch1, hist=hist, tech=tech,
        ic=ic, cal=cal, b_pts=b_pts, bias_items=b_items, sm_pts=sm_pts, sm_items=sm_items, total=total, outlook=outlook,
        n_sess=n_sess, sd_pct=sd_pct, touch=touch, outside=outside, rich=rich, str_theta=straddle_theta, pins=pins, exc=exc,
        vcond=vcond, vrp_pct=vrp_pct, d_n=d_n, d_v=d_v, pf=pf, tot_pcr=tot_pcr, bu_rows=bu_rows, bu_share=bu_share,
        build3=build3, old_date=old_date, ladder=ladder, cands=cands, best=best, calendar_expiry=e2,
        age_days=age_days, generated=f"{now_ist:%d %b %H:%M} IST", w=w, show_plan=SHOW_PLAN, eff_samples=(len(w['end']) // n_sess if w else 0), log8=log8, events=upcoming, risk_pct=RISK_PCT, pt=PROFIT_TARGET, sm=STOP_MULT, adj=ADJUST_ATR_MULT)
    page = R.render(ctx)
    docs = D.ROOT / "docs"
    docs.mkdir(exist_ok=True)


    brief = [f"# Nifty options brief - {day:%a %d %b %Y}", "",
             f"NIFTY {ts['close']:,.1f} ({ts['chg_pct']:+.2f}%) | VIX {vs['vix']:.2f} (at or above {vs['pctile']:.0f}% of past-year readings, {'high' if vs['pctile'] >= 75 else 'low' if vs['pctile'] <= 25 else 'middle range'} expected volatility relative to history) | Trend {ts['trend']}, ADX {ts['adx']:.0f} (trend strength)",
             f"Expiry {e1:%d %b} ({m1['dte']}d): ATM IV {m1['atm_iv']:.1f}% (annualised volatility priced near spot) | estimated move to expiry ±{m1['sd_move']:.0f} | straddle {m1['straddle']:.0f} | PCR {m1['pcr_oi']:.2f} ({100*m1['pcr_oi']:.0f} open puts per 100 calls, {'mild bullish vote' if m1['pcr_oi'] > 1.2 else 'mild bearish vote' if m1['pcr_oi'] < 0.7 else 'neutral vote'} in the model)",
             f"Walls (possible support / resistance): put {m1['put_wall']:.0f} / call {m1['call_wall']:.0f} | max pain {m1['max_pain']:.0f} (smallest payout at expiry) | gamma-OI strikes (where many options are sensitive to a price move) {', '.join(f'{p:.0f}' for p in pins)}",
             f"FII futures long {pv['fut_long_pct']:.0f}% | institutional positioning score {sm_pts:+d} ({sm_bias})" if pv else "FII data n/a",
             f"IRON CONDOR {ic[0]}/{ic[1]} {ic[2]} | 2:1 RATIO CALENDAR {cal[0]}/{cal[1]} {cal[2]} | OUTLOOK {outlook} ({total:+d})"]
    brief.append("Range strategy review: " + (trade_review["chosen"] or "None") + " | " + ("No trade: " + " ".join(trade_review["reasons"]) if trade_review["reasons"] else "Paper candidate"))
    if best:
        brief.append(f"Best condor: {best['buy_put']:.0f}/{best['sell_put']:.0f}P {best['sell_call']:.0f}/{best['buy_call']:.0f}C credit {best['credit']:.1f}, max loss ₹{best['max_loss_rs']:,.0f}, past-loss {best['hist'].get('lose_all', nan):.0f}%")
    brief.append(f"\nFull dashboard: docs/{ds}.html")
    if mode != "exchange":
        brief.insert(1, warnings[0])
    if events_until(e1) is None:
        brief.append("Event coverage unverified. Neither strategy received an event point.")
    D.save_snapshot(opts, futs, day)
    D.append_participants(day, part)
    if cash:
        D.atomic_write(D.CASH_FILE, all_cash.to_csv)
    D.atomic_write(D.DATA / "history" / "daily_metrics.csv", all_metrics.to_csv)
    if args.hist_file is None:
        D.atomic_write(D.HIST_FILE, lambda path: full_history.to_csv(path))
    reports = D.ROOT / "reports"
    brief_text = "\n".join(brief)
    D.atomic_write(docs / f"{ds}.html", lambda path: path.write_text(page, encoding="utf-8"))
    D.atomic_write(reports / f"{ds}.md", lambda path: path.write_text(brief_text, encoding="utf-8"))
    newest = max(path.stem for path in docs.glob("????-??-??.html"))
    if ds == newest:
        D.atomic_write(docs / "index.html", lambda path: path.write_text(page, encoding="utf-8"))
        D.atomic_write(reports / "latest.md", lambda path: path.write_text(brief_text, encoding="utf-8"))
    D.atomic_write(completed, lambda path: path.write_text(json.dumps(fingerprints())))
    print("Report written:", docs / f"{ds}.html")
    if mode == "exchange" and ds == newest:
        notify.send("\n".join(brief[:8]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    for a in ("--bhav-file", "--hist-file", "--part-file", "--cash-file", "--contract-file", "--date"):
        ap.add_argument(a)
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--force", action="store_true")
    build(ap.parse_args())
