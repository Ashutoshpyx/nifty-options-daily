"""Turns the computed numbers into one dense, dark, terminal-style HTML page (no external files)."""
import html

import numpy as np

CSS = """
:root{--bg:#050505;--pn:#0d0d0d;--bd:#262626;--tx:#d8d8d8;--mu:#7d828a;--am:#ffb000;--up:#00d26a;--dn:#ff4d4d;--cy:#4db8ff;--mg:#ff9f43}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;padding:8px;color:var(--tx);font:12px/1.35 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
 padding-top:max(8px,env(safe-area-inset-top));padding-bottom:max(8px,env(safe-area-inset-bottom))}
.top{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid var(--am);padding:2px 2px 6px;margin-bottom:6px}
.top h1{font-size:14px;margin:0;color:var(--am);letter-spacing:.08em}
.top span{color:var(--mu)}
.tick{display:flex;flex-wrap:wrap;gap:0;border:1px solid var(--bd);background:var(--pn);margin-bottom:8px}
.tick div{padding:5px 10px;border-right:1px solid var(--bd);min-width:92px}
.meaning{white-space:normal;color:var(--mu);font-weight:normal}.tick div{max-width:245px}.kv td:first-child,th{white-space:normal}.tick small{display:block;color:var(--mu);font-size:9px;letter-spacing:.06em}
.tick b{font-size:15px;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:8px;align-items:start}
.wide{grid-column:1/-1}
.pn{background:var(--pn);border:1px solid var(--bd);min-width:0}
.pn>h2{margin:0;padding:3px 8px;background:#161616;border-bottom:1px solid var(--bd);color:var(--am);font-size:11px;letter-spacing:.1em;font-weight:600}
.pn>.b{padding:6px 8px;overflow-x:auto}
table{border-collapse:collapse;width:100%;white-space:nowrap}
th{color:var(--mu);font-weight:400;text-align:right;padding:2px 6px;border-bottom:1px solid var(--bd);font-size:10px;letter-spacing:.04em}
td{padding:2px 6px;text-align:right;border-bottom:1px solid #151515}
th:first-child,td:first-child{text-align:left}
td.l,th.l{text-align:left}
.up{color:var(--up)}.dn{color:var(--dn)}.mu{color:var(--mu)}.am{color:var(--am)}.cy{color:var(--cy)}.mg{color:var(--mg)}
.big{font-size:22px;font-weight:700}
.score{display:flex;gap:6px}
.score div{flex:1;border:1px solid var(--bd);padding:6px 8px;text-align:center}
.score small{display:block;color:var(--mu);font-size:9px;letter-spacing:.08em}
.score i{font-style:normal;font-size:10px;letter-spacing:.06em}
tr.hl td{background:#1b1600;color:var(--am)}
tr.atm td{background:#13202b}
tr.spot td{background:#2a2200;color:var(--am);font-weight:700}
td.bar{position:relative;min-width:84px}
td.bar i{position:absolute;top:1px;bottom:1px;opacity:.38}
td.bar b{position:relative;font-weight:400}
td.cb i{right:0;background:var(--dn)}td.pb i{left:0;background:var(--up)}
td.cb{text-align:right}td.pb{text-align:left}
td.wall b{font-weight:700;color:#fff}
.kv td:first-child{color:var(--mu)}
.kv td:last-child{color:var(--tx)}
ul{margin:0;padding:0;list-style:none}li{padding:1px 0}
.ch{width:100%;max-width:760px;height:auto;display:block;margin:0 auto}.ch text{fill:var(--mu);font-size:9px;font-family:inherit}
.note{color:var(--mu);font-size:10px;padding-top:4px}
.warn{border:1px solid var(--am);color:var(--am);padding:4px 8px;margin-bottom:8px}
.lad td{padding:1px 6px}.lad td:nth-child(2),.lad th:nth-child(2){text-align:left;white-space:normal}
@media(max-width:600px){.tick div{min-width:78px;padding:4px 7px}.big{font-size:19px}}
"""


def E(x): return html.escape(str(x))
def n0(x): return "-" if x != x else f"{x:,.0f}"
def n1(x): return "-" if x != x else f"{x:,.1f}"
def n2(x): return "-" if x != x else f"{x:,.2f}"
def pc(x): return "-" if x != x else f"{x:.0f}%"
def lk(x): return f"{x / 1e5:,.1f}"
def cls(x): return "up" if x > 0 else "dn" if x < 0 else "mu"
def sp(c_, t): return f'<span class="{c_}">{t}</span>'
def lab(t, tip):
    return f'{t} <span class="meaning">({E(tip)})</span>' 


def chip(state, kind="check"):
    if kind == "check":
        return sp("up", "✓") if state == 1 else sp("dn", "✗") if state == -1 else sp("mu", "–")
    return sp("up", "▲") if state == 1 else sp("dn", "▼") if state == -1 else sp("mu", "●")


def panel(title, body, wide=False):
    return f'<section class="pn{" wide" if wide else ""}"><h2>{title}</h2><div class="b">{body}</div></section>'


def table(header, rows, cls_="", hl=None, rowcls=None):
    h = "".join(f"<th>{c}</th>" for c in header)
    out = []
    for i, r in enumerate(rows):
        c_ = rowcls[i] if rowcls and rowcls[i] else ("hl" if hl is not None and i == hl else "")
        out.append(f'<tr class="{c_}">' + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    return f'<table class="{cls_}"><tr>{h}</tr>{"".join(out)}</table>'


def kv(rows):
    return '<table class="kv">' + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows) + "</table>"


# ---------------------------------------------------------------- svg
def svg_lines(series, w=560, h=170, hlines=(), xlabels=("", ""), yfmt="{:,.0f}"):
    L, R, T, B = 46, 8, 14, 16
    xs = np.concatenate([np.asarray(s["x"], float) for s in series])
    ys = np.concatenate([np.asarray(s["y"], float) for s in series] + [np.array([v for v, *_ in hlines], float)])
    ys = ys[~np.isnan(ys)]
    lo, hi = ys.min(), ys.max()
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    x0, x1 = xs.min(), xs.max()
    X = lambda x: L + (x - x0) / ((x1 - x0) or 1) * (w - L - R)
    Y = lambda y: T + (1 - (y - lo) / ((hi - lo) or 1)) * (h - T - B)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#1c1c1c"/>'
                 f'<text x="{L - 4}" y="{Y(v) + 3:.1f}" text-anchor="end">{yfmt.format(v)}</text>')
    for v, name, col in hlines:
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{col}" stroke-dasharray="3 3"/>'
                 f'<text x="{w - R - 2}" y="{Y(v) - 2:.1f}" text-anchor="end" style="fill:{col}">{E(name)}</text>')
    lx = L + 4
    for s in series:
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(s["x"], s["y"]) if b == b)
        o.append(f'<polyline fill="none" stroke="{s["c"]}" stroke-width="{s.get("sw", 1.3)}" points="{pts}"/>')
        o.append(f'<text x="{lx}" y="9" style="fill:{s["c"]}">{E(s["n"])}</text>')
        lx += 9 * (len(s["n"]) + 2)
    o.append(f'<text x="{L}" y="{h - 3}">{E(xlabels[0])}</text><text x="{w - R}" y="{h - 3}" text-anchor="end">{E(xlabels[1])}</text></svg>')
    return "".join(o)


def svg_oi(ch, m, w=640, h=230):
    s = ch[(ch.index > m["spot"] * 0.94) & (ch.index < m["spot"] * 1.06)]
    L, R = 40, 6
    n = len(s)
    slot = (w - L - R) / n
    bw = slot * 0.42
    top_h, gap, bot_h = 130, 14, 60
    mx = max(s.ce_oi.max(), s.pe_oi.max()) or 1
    md = max(s.ce_doi.abs().max(), s.pe_doi.abs().max()) or 1
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    base = 14 + top_h
    for i, (k, r) in enumerate(s.iterrows()):
        x = L + i * slot
        hp, hc = r.pe_oi / mx * top_h, r.ce_oi / mx * top_h
        o.append(f'<rect x="{x:.1f}" y="{base - hp:.1f}" width="{bw:.1f}" height="{hp:.1f}" fill="#00d26a" opacity=".8"/>'
                 f'<rect x="{x + bw:.1f}" y="{base - hc:.1f}" width="{bw:.1f}" height="{hc:.1f}" fill="#ff4d4d" opacity=".8"/>')
        mid = base + gap + bot_h / 2
        for off, d, col in ((0, r.pe_doi, "#00d26a"), (bw, r.ce_doi, "#ff4d4d")):
            dh = d / md * bot_h / 2
            o.append(f'<rect x="{x + off:.1f}" y="{min(mid, mid - dh):.1f}" width="{bw:.1f}" height="{abs(dh):.1f}" fill="{col}" opacity=".7"/>')
        if i % max(1, n // 8) == 0:
            o.append(f'<text x="{x + bw:.1f}" y="{h - 2}" text-anchor="middle">{k:.0f}</text>')
    xs = lambda v: L + (np.searchsorted(s.index.values, v) + 0.5) * slot
    for j, (v, name, col) in enumerate(((m["spot"], "SPOT", "#ffb000"), (m["max_pain"], "MAX PAIN", "#c58cff"))):
        o.append(f'<line x1="{xs(v):.1f}" x2="{xs(v):.1f}" y1="12" y2="{h - 12}" stroke="{col}" stroke-dasharray="3 3"/>'
                 f'<text x="{xs(v) + 3:.1f}" y="{22 + 11 * j}" style="fill:{col}">{name} {v:.0f}</text>')
    o.append(f'<text x="2" y="24">OI {mx / 1e5:.0f}L</text><text x="2" y="{base + gap + 8}">chg</text></svg>')
    return "".join(o)


def svg_hist(end, sd_pct, be_lo, be_hi, spot, w=560, h=150):
    cnt, edges = np.histogram(end * 100, bins=44)
    L, R, T, B = 6, 6, 14, 16
    X = lambda x: L + (x - edges[0]) / (edges[-1] - edges[0]) * (w - L - R)
    Yh = lambda c_: T + (1 - c_ / cnt.max()) * (h - T - B)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    if be_lo:
        a, b = (be_lo / spot - 1) * 100, (be_hi / spot - 1) * 100
        o.append(f'<rect x="{X(a):.1f}" y="{T}" width="{X(b) - X(a):.1f}" height="{h - T - B}" fill="#00d26a" opacity=".13"/>')
    for i, c_ in enumerate(cnt):
        o.append(f'<rect x="{X(edges[i]):.1f}" y="{Yh(c_):.1f}" width="{(w - L - R) / len(cnt) - 1:.1f}" height="{h - B - Yh(c_):.1f}" fill="#5d6570"/>')
    for v in (sd_pct * 100, -sd_pct * 100):
        o.append(f'<line x1="{X(v):.1f}" x2="{X(v):.1f}" y1="{T}" y2="{h - B}" stroke="#4db8ff" stroke-dasharray="3 3"/>')
    o.append(f'<text x="{L}" y="10" style="fill:#4db8ff">blue = options 1 SD ({sd_pct * 100:.2f}%)</text>'
             f'<text x="{L}" y="{h - 3}">{edges[0]:.1f}%</text><text x="{w - R}" y="{h - 3}" text-anchor="end">{edges[-1]:.1f}%</text></svg>')
    return "".join(o)


# ---------------------------------------------------------------- page
def render(c):
    ts, vs, m1, pv = c["ts"], c["vs"], c["m1"], c["pv"]
    day = c["day"]
    P = []

    # ---------- ticker
    def tk(label, val, sub=""):
        return f"<div><small>{label}</small><b>{val}</b>{(' ' + sub) if sub else ''}</div>"
    rank = vs["pctile"]
    vol_label = "high" if rank >= 75 else "low" if rank <= 25 else "middle range"
    vol_read = (f"({vol_label} for the past year. About {rank:.0f}% of readings were at or below today’s level. "
                "Higher VIX means options price in wider swings in either direction.)")
    ratio = m1["pcr_oi"]
    bias = "one mildly bullish vote" if ratio > 1.2 else "one mildly bearish vote" if ratio < 0.7 else "neutral vote"
    pcr_read = (f"({100 * ratio:.0f} open puts per 100 open calls. The model gives this {bias}. "
                "Open positions can include hedges.)") if ratio == ratio else "(Reading unavailable)"
    tick = "".join([
        tk("NIFTY 50", f"{ts['close']:,.1f}", sp(cls(ts["chg"]), f"{ts['chg_pct']:+.2f}%")),
        tk("INDIA VIX", f"{vs['vix']:.2f}", sp(cls(-vs["chg"]), f"{vs['chg_pct']:+.1f}%")),
        tk("VIX PCTILE", f"{vs['pctile']:.0f}", sp("mu", vol_read if rank == rank else "(History unavailable)")),
        tk("PCR OI", f"{m1['pcr_oi']:.2f}", sp("mu", pcr_read)),
        tk("ATM IV", f"{m1['atm_iv']:.1f}%", sp("mu", f"(Volatility priced into options near today’s NIFTY level, expressed per year. For {c['e1']:%d %b}, this implies roughly ±{m1['sd_move']:.0f} points.)")),
        tk("1SD MOVE", f"±{m1['sd_move']:.0f}", sp("mu", f"{c['n_sess']}d")),
        tk("PUT / CALL WALL", f"{m1['put_wall']:.0f} / {m1['call_wall']:.0f}", "(Large put and call positions. Watch the first level for possible buying support and the second for possible selling pressure. Either can break.)"),
        tk("MAX PAIN", f"{m1['max_pain']:.0f}", sp(cls(m1["max_pain"] - m1["spot"]), f"({m1['max_pain'] - m1['spot']:+.0f} points from spot. At this expiry level the total payout on open options would be smallest. Price can settle elsewhere.)")),
        tk("FII % LONG (share of foreign investors’ open index futures held long)", f"{pv['fut_long_pct']:.0f}" if pv else "n/a", sp("mu", "idx fut")),
        tk("OUTLOOK", sp("up" if c["total"] >= 2 else "dn" if c["total"] <= -2 else "am", c["outlook"].upper()), sp("mu", f"{c['total']:+d}")),
    ])

    review = c["trade_review"]
    note = lambda msg: '<p class="note">' + msg + '</p>'
    chosen = review["chosen"]
    verdict = "No trade" if review["reasons"] else "Paper candidate"
    decision = note(f"<b>{verdict}</b> · {E(c['outlook'])} view · {E(chosen or 'No qualifying structure')}. " + E(" ".join(review["reasons"])))
    if review["week"]:
        lo,mid,hi,count = review["week"]
        decision += note(f"Next five sessions: {lo:,.0f} to {hi:,.0f} central historical closing range, median {mid:,.0f}. Based on {count} overlapping windows at similar starting VIX. Today's near-expiry trade spans {c['n_sess']} trading session(s).")
    if review["validation"]:
        rate, n = review["validation"]
        decision += note(f"Historical check: the five-session closing band contained {rate:.0%} of {n} later five-session closes in a rolling replay. This checks the price range only.")
    decision += note(f"Sell front expiry {c['e1']:%d %b}. Calendar hedges expire {c['calendar_expiry']:%d %b}. Compared {review['total']} eligible structures. All prices are settlement marks before costs.")
    for name,r in review["picks"].items():
        risk = (f"Gross maximum loss ₹{r['loss']:,.0f}. Gross maximum profit ₹{r['profit']:,.0f}." if r["loss"] is not None else
                "Extra short call has unlimited upside loss." if name=="2:1 double calendar" else "One long for one short. Value at front expiry depends on remaining IV.")
        decision += kv([("Structure",name),("Legs",E(r["legs"])),("Entry", f"₹{abs(r['net']):,.0f} " + ("credit" if r["net"]>0 else "debit")),
                        ("Risk",risk),("Touched a sold strike",f"{100*r['touch']:.1f}% of {r['count']} historical windows"),
                        ("Median model P&L",f"₹{r['median']:,.0f} at front expiry, unchanged later IV"),
                        ("Worst evaluated P&L",f"₹{r['stress']:,.0f} (condor expiry limit, or calendar scenarios including ±10% spot and −3 IV points)")])
        if r["scenario"]:
            decision += table(["Later IV at front expiry","Spot unchanged","Spot −10%","Spot +10%"],
                              [[label,*[f"₹{v:,.0f}" for v in vals]] for label,vals in
                               zip(["Unchanged","Down 3 points"],r["scenario"])])
    decision += note("Low VIX favours reviewing a calendar only with positive model decay, positive median scenario P&L, a suitable near/far IV gap and stable VIX. Mild bullishness puts the short call farther away than the short put; mild bearishness reverses the distances. Strong bullish or bearish scores screen only a one-sided put or call calendar respectively. Historical frequencies and scenario P&L are research estimates.")
    P.append(panel("Trade decision and strike review",decision,True))
    # ---------- scores
    def sbox(name, s, n, verdict):
        col = "up" if verdict == "FAVOURABLE" else "am" if verdict == "SELECTIVE" else "dn"
        return f'<div><small>{name}</small><span class="big {col}">{s}/{n}</span><br><i class="{col}">{verdict}</i></div>'
    dirv = c["outlook"].upper()
    dcol = "up" if c["total"] >= 2 else "dn" if c["total"] <= -2 else "am"
    scores = ('<div class="score">' + sbox("IRON CONDOR", c["ic"][0], c["ic"][1], c["ic"][2]) + sbox("2:1 RATIO CALENDAR", c["cal"][0], c["cal"][1], c["cal"][2])
              + f'<div><small>DIRECTION</small><span class="big {dcol}">{c["total"]:+d}</span><br><i class="{dcol}">{dirv}</i></div></div>')
    chg = "<ul>" + "".join(f"<li>{E(x)}</li>" for x in c["changes"]) + "</ul>"
    P.append(panel("SIGNAL BOARD", scores + '<div class="note">CHANGED SINCE LAST REPORT</div>' + chg))

    def checks(items):
        return table(["Check", "Value", "Rule", ""], [[i["label"], E(i["value"]), sp("mu", E(i["rule"])), chip(i["state"])] for i in items])
    P.append(panel(f"IRON CONDOR CHECKS {c['ic'][0]}/{c['ic'][1]}", checks(c["ic"][3])))
    P.append(panel(f"2:1 RATIO CALENDAR MARKET CHECKS {c['cal'][0]}/{c['cal'][1]}", checks(c["cal"][3])))
    rows = [[i["label"], E(i["value"]), chip(i["state"], "bias")] for i in c["bias_items"]] + \
           [[sp("am", i["label"]), E(i["value"]), chip(i["state"], "bias")] for i in c["sm_items"]]
    votes = table(["Input", "Reading", "Direction"], rows)


    # ---------- ladder
    spot = m1["spot"]
    level_notes = {'Pivot R2': 'second upper reference where a rally may meet sellers', 'Pivot R1': 'first upper reference where a rally may meet sellers', 'Pivot PP': 'central reference from the last session’s high, low and close', 'Pivot S1': 'first lower reference where buyers may appear', 'Pivot S2': 'second lower reference where buyers may appear', 'Gamma-OI strike': 'many open options weighted by how quickly their price sensitivity changes here. Watch for a reaction in either direction', 'Max pain': 'expiry level with the smallest combined payout on open options', '90% history up': 'about 9 in 10 past windows had a smaller or equal peak rise. The remaining windows rose farther', '90% history down': 'about 9 in 10 past windows had a smaller or equal fall at their lowest point', '1 SD up (options)': 'upper estimate of the move priced to expiry', '1 SD down (options)': 'lower estimate of the move priced to expiry', 'SPOT': 'current index level', 'Call OI wall': 'large open call position, possible resistance', 'Put OI wall': 'large open put position, possible support', 'EMA': 'average close giving more weight to recent sessions', 'Screen candidate short': 'example strike being considered for sale'}
    groups = {}
    for v_, name_, kind_ in c["ladder"]:
        if abs(v_ - spot) <= spot * 0.03:
            meaning = next((v for prefix, v in level_notes.items() if name_.startswith(prefix)), "")
            if meaning:
                name_ += f" ({meaning})"
            groups.setdefault(round(v_), []).append((name_, kind_))
    prio = ["res", "sup", "trade", "mp", "pin", "band", "hist", "tech"]
    lv = [(k_, " · ".join(dict.fromkeys(n_ for n_, _ in it_)), min((kk for _, kk in it_), key=prio.index)) for k_, it_ in groups.items()]
    lv.append((spot, "SPOT (current index level)", "spot"))
    lv.sort(key=lambda t: -t[0])
    kc = {"res": "dn", "sup": "up", "band": "cy", "hist": "mg", "mp": "am", "pin": "am", "tech": "", "trade": "cy", "spot": "am"}
    rows, rc = [], []
    for k, (v, name, kind) in enumerate(lv):
        near = sum(1 for u in lv if u is not lv[k] and u[2] != "spot" and abs(u[0] - v) <= 40) if kind != "spot" else 0
        star = sp("am", "★") if near else ""
        rows.append([f"{v:,.0f}", sp(kc.get(kind, ""), E(name)), f"{v - spot:+.0f}", f"{100 * (v / spot - 1):+.2f}%", star])
        rc.append("spot" if kind == "spot" else "")
    P.append(panel("Prices to watch above and below NIFTY", note(f"Start at SPOT ({spot:,.0f}). A positive distance is above today’s close. An OI wall is a strike with many open positions. A pivot is calculated from the previous session’s prices. ★ groups readings within 40 points. It adds no extra vote or guarantee of support.") + table(["Level", "What", "Pts", "%", ""], rows, "lad", rowcls=rc)))

    # ---------- weekly expiry
    rich = c["rich"]
    rich_t = "" if rich != rich else (sp("up", "above historical move") if rich > 1.1 else sp("dn", "below historical move") if rich < 0.9 else sp("mu", "near historical move"))
    wk = kv([
        (lab("Expiry / days / sessions", "Calendar days and trading sessions left"), f"{c['e1']:%d %b} / {m1['dte']} / {c['n_sess']}"),
        (lab("ATM straddle", "Call + put at the ATM strike"), f"₹{m1['straddle']:.0f}  (₹{m1['straddle'] * m1['lot']:,.0f}/lot)"),
        ("Straddle breakevens", f"{m1['atm'] - m1['straddle']:,.2f} - {m1['atm'] + m1['straddle']:,.2f}"),
        (lab("Straddle decay / day", "How many points the straddle loses per day"), f"{c['str_theta']:.1f} pts ({100 * c['str_theta'] / m1['straddle']:.0f}%)  ₹{c['str_theta'] * m1['lot']:,.0f}/lot"),
        (lab("1 SD move", "Option-implied one standard deviation move to expiry"), f"±{m1['sd_move']:.0f} pts (±{c['sd_pct'] * 100:.2f}%)  {spot - m1['sd_move']:,.0f} - {spot + m1['sd_move']:,.0f}"),
        (lab("Implied / historical move", "Options' 1SD divided by what Nifty typically moved over the same number of sessions"), f"{n2(rich)}x {rich_t}"),
        (lab("Past 3y: touched / closed outside 1SD", "Share of past windows where high/low reached, or close ended beyond, the 1SD band"), f"{pc(c['touch'])} / {pc(c['outside'])}"),
        (lab("Skew (put IV - call IV)", "Positive: downside protection costs more"), n1(m1["skew"])),
        (lab("Gamma-OI strikes", "Model gamma x total OI. Shows where option activity is concentrated. Not a price-pin forecast and not dealer gamma exposure"), ", ".join(f"{p:.0f}" for p in c["pins"]) or "-"),
    ])
    if c["exc"]:
        wk += table(["History %", "Up", "Level", "Down", "Level"],
                    [[f"{q}%", f"+{u:.0f}", f"{spot + u:,.0f}", f"-{d:.0f}", f"{spot - d:,.0f}"] for q, u, d in c["exc"]])
    wk += table(["Expiry", "DTE (days to expiry)", "IV", "Straddle", "1SD", "PCR", "Max pain", "Skew"],
                [[f"{e:%d%b}{'*' if mets_m['monthly'] else ''}", mets_m["dte"], n1(mets_m["atm_iv"]), f"{mets_m['straddle']:.0f}", f"±{mets_m['sd_move']:.0f}",
                  n2(mets_m["pcr_oi"]), f"{mets_m['max_pain']:.0f}", n1(mets_m["skew"])] for e, mets_m in ((e, c["mets"][e]) for e in c["exps"])])
    P.append(panel(f"WEEKLY EXPIRY {c['e1']:%d %b}", note(f"The {m1['atm']:,.0f} straddle buys both a call and a put. At expiry the buyer needs a move beyond a breakeven to cover the premium and then costs. Decay estimates one calendar day with forward and IV fixed. The 1 SD band estimates the scale of a move. A touch includes intraday highs and lows, while closed outside uses only the final close.") + wk))

    # ---------- vol
    vc = c["vcond"]
    vol = kv([
        ("India VIX", f"{vs['vix']:.2f} (30-day volatility implied by options, expressed per year)"),
        ("1d / 5d change", f"{sp(cls(-vs['chg_pct']), f'{vs['chg_pct']:+.1f}%')} / {sp(cls(-vs['chg5_pct']), f'{vs['chg5_pct']:+.1f}%')}"),
        (lab("Percentile / IV rank (1y)", "Where VIX sits versus the last year"), f"{vs['pctile']:.0f} / {vs['ivrank']:.0f}   range {vs['lo']:.1f}-{vs['hi']:.1f}"),
        ("VIX vs 20d avg", f"{vs['vix']:.2f} vs {vs['avg20']:.2f}"),
        (lab("Actual vol 10d / 20d", "How much Nifty really moved, annualised"), f"{ts['hv10']:.1f} / {ts['hv20']:.1f}"),
        (lab("VIX minus trailing vol (rank)", "Backward-looking: VIX minus the last 20 days of actual movement, and its rank over a year. Not a true forward risk premium"), f"{vs['vix'] - ts['hv20']:+.1f}  ({pc(c['vrp_pct'])})"),
        ("Implied move / day, week", f"±{vs['daily_move_pct']:.2f}% / ±{vs['weekly_move_pct']:.2f}%  (±{spot * vs['daily_move_pct'] / 100:.0f} / ±{spot * vs['weekly_move_pct'] / 100:.0f} pts)"),
        ("Weekly ATM IV vs VIX", f"{m1['atm_iv']:.1f} vs {vs['vix']:.1f}  ({m1['atm_iv'] - vs['vix']:+.1f})"),
        ("5d Nifty / VIX", f"{sp(cls(c['d_n']), f'{c['d_n']:+.1f}%')} / {sp(cls(-c['d_v']), f'{c['d_v']:+.1f}%')}"),
    ])
    if vc:
        vol += (f'<div class="note">{vc["n"]} past days with similar VIX: higher after {vc["horizon"]}d {vc["up_share"]:.0f}% of the time, '
                f'avg {vc["mean_chg"]:+.1f}%; Nifty avg move {vc["avg_abs_nifty"]:.1f}%</div>')
    P.append(panel("How large a move is priced in?", note(f"India VIX measures the annualised volatility implied for the next 30 calendar days. At {vs['vix']:.2f} it exceeds or equals about {vs['pctile']:.0f}% of readings in the past year. Weekly IV ({m1['atm_iv']:.1f}%) covers a different expiry. Rising volatility makes a fixed distance to a sold strike less protective.") + vol))

    # ---------- tech
    pv_l = ts["pivots"]
    tech = kv([
        ("Trend", f"{sp('am', ts['trend'])}  ADX {ts['adx']:.0f} (+{ts['pdi']:.0f}/-{ts['mdi']:.0f})  weekly {'above' if ts['weekly_above_ema20'] else 'below'} 20w EMA"),
        ("EMA 20/50/100/200", f"{ts['ema20']:,.0f} / {ts['ema50']:,.0f} / {ts['ema100']:,.0f} / {ts['ema200']:,.0f}"),
        ("RSI / MACD hist (momentum relative to its recent trend)", f"{ts['rsi']:.0f} / {ts['macd_hist']:+.1f}"),
        ("ATR(14) (typical daily range over 14 sessions)", f"{ts['atr']:.0f} pts ({ts['atr_pct']:.2f}%)  today {ts['range_vs_atr']:.1f}x"),
        ("Bollinger %B / width (position inside the price band and how wide it is)", f"{ts['bb_pctb']:.2f} / {ts['bb_width']:.1f}%  {sp('am', 'SQUEEZE') if ts['bb_width_pct'] < 20 else ''}"),
        ("20d hi / lo", f"{ts['hi20']:,.0f} / {ts['lo20']:,.0f}"),
        ("52w hi / lo", f"{ts['hi52']:,.0f} ({100 * (ts['close'] / ts['hi52'] - 1):+.1f}%) / {ts['lo52']:,.0f} ({100 * (ts['close'] / ts['lo52'] - 1):+.1f}%)"),
        ("Close in day range", f"{ts['close_pos'] * 100:.0f}%"),
    ])
    tech += table(["S3", "S2", "S1", "PIVOT", "R1", "R2", "R3"],
                  [[f"{pv_l[k]:,.0f}" for k in ("S3", "S2", "S1", "P", "R1", "R2", "R3")]])
    P.append(panel("Market direction | trend, momentum and positioning", note(
        f"{E(c['outlook'])}. Price and open-interest rules scored {c['b_pts']:+d}. "
        f"Institutional positioning and cash-flow rules scored {c['sm_pts']:+d}. "
        "EMA is an average that favours recent prices. ADX measures trend strength, RSI measures recent momentum, "
        "and ATR is the typical daily range in points. Several votes use the same prices and can move together.") + tech + votes, True))

    # ---------- charts
    P.append(panel(f"OPEN INTEREST PROFILE {c['e1']:%d %b}  (top: OI, bottom: change today)", svg_oi(c["ch1"], m1), True))
    h = c["hist"].iloc[-120:]
    t = c["tech"].iloc[-120:]
    xo = lambda idx: [d.toordinal() for d in idx]
    P.append(panel("NIFTY 120D  close / EMA20 / EMA50 / EMA200", svg_lines(
        [dict(n="CLOSE", x=xo(h.index), y=h.n_close.values, c="#e8e8e8", sw=1.5), dict(n="EMA20", x=xo(t.index), y=t.ema20.values, c="#4db8ff"),
         dict(n="EMA50", x=xo(t.index), y=t.ema50.values, c="#ffb000"), dict(n="EMA200", x=xo(t.index), y=t.ema200.values, c="#ff4d4d")],
        xlabels=(f"{h.index[0]:%d %b}", f"{h.index[-1]:%d %b}"))))
    v = c["hist"]["vix"].dropna().iloc[-252:]
    P.append(panel("INDIA VIX 1Y", svg_lines(
        [dict(n="VIX", x=xo(v.index), y=v.values, c="#c58cff", sw=1.5)],
        hlines=[(v.quantile(.2), "20p", "#555"), (v.quantile(.5), "50p", "#777"), (v.quantile(.8), "80p", "#555")],
        xlabels=(f"{v.index[0]:%d %b %y}", f"{v.index[-1]:%d %b}"), yfmt="{:.1f}")))
    ivs = []
    for e, col in zip(c["exps"][:3], ["#4db8ff", "#ffb000", "#00d26a"]):
        s = c["chains"][e]
        s = s[(s.index > spot * 0.96) & (s.index < spot * 1.04)]
        ivs.append(dict(n=f"{e:%d%b}", x=s.index.values, y=s.iv.values * 100, c=col))
    P.append(panel("IV SMILE % (how much movement options price at different strikes)  (by expiry)", svg_lines(ivs, hlines=[(vs["vix"], "VIX", "#555")], xlabels=("lower strikes", "higher strikes"), yfmt="{:.1f}")))
    if c["w"]:
        best = next(iter(c["cands"]), None)
        P.append(panel(f"How NIFTY closed over {c['w']['n']} trading session(s)", note("Each bar counts past closing moves of that size. Taller bars mean more observations. Blue lines mark today’s implied move." + (" Green shading spans the first screened condor’s expiry breakevens. A path can cross a sold strike and finish back inside this area." if best else "")) +
                       svg_hist(c["w"]["end"], c["sd_pct"], best["be_low"] if best else None, best["be_high"] if best else None, spot)))

    # ---------- option chain
    ch, m = c["ch1"], m1
    sub = ch[(ch.index >= m["atm"] - 9 * 50) & (ch.index <= m["atm"] + 9 * 50)]
    mx = max(sub.ce_oi.max(), sub.pe_oi.max()) or 1
    cw, pw = {k for k, _ in m["resist"][:1]}, {k for k, _ in m["support"][:1]}
    body = ['<table><tr><th>CALL OI (open units in lakhs)</th><th>chg (change in open units, lakhs)</th><th>IV (priced volatility, %)</th><th>EOD price</th><th>STRIKE</th><th>EOD price</th><th>IV (priced volatility, %)</th><th>chg (change in open units, lakhs)</th><th>PUT OI (open units in lakhs)</th></tr>']
    for k, r in sub.iterrows():
        dcls = lambda d: "cy" if d > 0 else "mg" if d < 0 else "mu"
        tag = ' class="atm"' if k == m["atm"] else ""
        body.append(
            f'<tr{tag}><td class="bar cb{" wall" if k in cw else ""}"><i style="width:{100 * r.ce_oi / mx:.0f}%"></i><b>{lk(r.ce_oi)}</b></td>'
            f'<td class="{dcls(r.ce_doi)}">{r.ce_doi / 1e5:+.1f}</td><td>{n1(r.ce_iv * 100)}</td><td>{r.ce_px:.1f}</td>'
            f'<td class="am" style="text-align:center"><b>{k:.0f}</b></td>'
            f'<td>{r.pe_px:.1f}</td><td>{n1(r.pe_iv * 100)}</td><td class="{dcls(r.pe_doi)}">{r.pe_doi / 1e5:+.1f}</td>'
            f'<td class="bar pb{" wall" if k in pw else ""}"><i style="width:{100 * r.pe_oi / mx:.0f}%"></i><b>{lk(r.pe_oi)}</b></td></tr>')
    body.append("</table>")
    P.append(panel(f"OPTION CHAIN {c['e1']:%d %b}  (ATM highlighted; white = highest OI wall)", "".join(body), True))

    # ---------- OI flow
    pf = c["pf"]
    flow = table(["Expiry", "OI", "Vol", "Near-5%", "Change"],
                 [[f"{e:%d%b}", n2(pf[e]["pcr_oi"]), n2(pf[e]["pcr_vol"]), n2(pf[e]["pcr_near"]), n2(pf[e]["pcr_change"])] for e in c["exps"]])
    flow += f'<div class="note">PCR: OI = standing, Vol = today, Near-5% = within 5% of spot, Change = today\'s new positions. All expiries OI PCR {c["tot_pcr"]:.2f}</div>'
    ll = lambda lst: ", ".join(f"{k:.0f} ({lk(v)})" for k, v in lst) or "-"
    flow += kv([("Support (put OI)", ll(m["support"])), ("Resistance (call OI)", ll(m["resist"])),
                ("Put OI added (new open positions)", ll(m["fresh_put_writing"])), ("Call OI added (new open positions)", ll(m["fresh_call_writing"])),
                ("Put unwinding", ll(m["put_unwinding"])), ("Call unwinding", ll(m["call_unwinding"])),
                ("Net OI chg puts below / calls above", f"{m['net_put_doi'] / 1e5:+.1f}L / {m['net_call_doi'] / 1e5:+.1f}L")])
    P.append(panel("PCR | How many puts are open for every 100 calls?", note(f"For {c['e1']:%d %b}, put OI divided by call OI is {m['pcr_oi']:.2f}. That means about {100*m['pcr_oi']:.0f} open put units per 100 call units. Every contract has a buyer and seller. Protective put buying and put selling can both increase this ratio. Inspect the strikes, changes and price trend before interpreting it.") + flow))
    act = ""
    if c["bu_rows"]:
        act = table(["Strike", "OI chg", "Price", "Activity", "View"],
                    [[f"{r['strike']:.0f}{r['kind']}", f"{r['doi'] / 1e5:+.1f}L", f"{r['px']:.1f} ({r['dpx']:+.1f})", r["label"],
                      sp("up" if r["view"] == "bullish" else "dn", r["view"])] for r in c["bu_rows"]])
        act += f'<div class="note">Option activity by OI size: {sp("up", pc(c["bu_share"]["bull"]) + " bullish")} / {sp("dn", pc(c["bu_share"]["bear"]) + " bearish")}</div>'
    b3 = c["build3"]
    if b3:
        act += f'<div class="note">BUILD-UP SINCE {c["old_date"]}</div>' + kv([
            ("Calls added", ll(b3["calls_added"])), ("Puts added", ll(b3["puts_added"])), ("Calls cut", ll(b3["calls_cut"])), ("Puts cut", ll(b3["puts_cut"]))])
    P.append(panel("What changed at each strike?", note("Buying / long build-up (price and OI rose). Writing / short build-up (price fell as OI rose). Short covering (price rose as OI fell, consistent with some sellers buying back). Long unwinding (price and OI fell, consistent with some buyers closing). These labels infer activity from two changes. The file does not identify who initiated each trade.") + act or '<span class="mu">n/a</span>'))

    # ---------- FII
    fut = c["fut"]
    fb = note("Short covering (price rose while open positions fell, consistent with shorts buying back). Long build-up (price and open positions rose, consistent with new buying). Short build-up (price fell while positions rose). Long unwinding (price and positions fell). FII index futures cover multiple indices.")
    if fut:
        fb += kv([(f"Nifty futures {fut['expiry']:%d %b}", f"{fut['close']:,.1f} ({sp(cls(fut['chg_pct']), f'{fut['chg_pct']:+.2f}%')})  OI {fut['doi_pct']:+.1f}%  {sp('am', fut['label'].upper())}"),
                  ("Premium", f"{fut['basis']:+.0f} pts  ({fut['basis_ann']:.1f}% a year)")])
    if c["part"]:
        rows = []
        for who in ("FII", "DII", "Pro", "Client"):
            if who in c["part"]:
                p = c["part"][who]
                d = pv.get("d_fut_net") if (who == "FII" and pv) else None
                rows.append([who, n0(p["fut_long"]), n0(p["fut_short"]), sp(cls(p["fut_net"]), f"{p['fut_net']:+,.0f}"), f"{p['fut_long_pct']:.0f}%",
                             sp(cls(d), f"{d:+,.0f}") if d == d and d is not None else "-",
                             f"{n0(p['call_long'])}/{n0(p['call_short'])}", f"{n0(p['put_long'])}/{n0(p['put_short'])}"])
        fb += table(["Who", "Fut long (positions that gain on a rise)", "Fut short (positions that gain on a fall)", "Net", "%L", "Net chg", "Calls L/S", "Puts L/S"], rows, hl=0)
    cl = c["clog"]
    if len(cl):
        last = cl.tail(6).iloc[::-1]
        fb += table(["Cash Rs cr", "FII", "DII"], [[i, sp(cls(r.fii_net), f"{r.fii_net:+,.0f}"),
                    sp(cls(r.dii_net), f"{r.dii_net:+,.0f}") if "dii_net" in r.index and r.dii_net == r.dii_net else "-"] for i, r in last.iterrows()])
        totals = [f"{n}d {v:+,.0f}" if v is not None else f"{n}d unavailable" for n, v in c["cash_totals"].items()]
        fb += '<div class="note">FII net ' + " / ".join(totals) + '</div>' 
    P.append(panel("FUTURES, FII / DII (foreign and domestic institutional investors)", fb or '<span class="mu">n/a</span>'))

    # ---------- condor desk
    cands, best = c["cands"], c["best"]
    if cands:
        col = lambda v, a, b: "up" if v <= a else "am" if v <= b else "dn"
        rows = []
        for r in cands:
            h_ = r["hist"] or {}
            both = lambda a_, b_: f'{sp(col(h_[a_], 15, 30), pc(h_[a_]))} | {sp(col(h_[b_], 15, 30), pc(h_[b_]))}' if a_ in h_ and b_ in h_ else (sp(col(h_[a_], 15, 30), pc(h_[a_])) + " | -" if a_ in h_ else "-")
            rows.append([f"{r['delta']:.2f}", f"{r['buy_put']:.0f}/{r['sell_put']:.0f}P  {r['sell_call']:.0f}/{r['buy_call']:.0f}C",
                         f"{r['credit']:.1f}", f"₹{r['credit_rs']:,.0f}", f"₹{r['max_loss_rs']:,.0f}", f"{r['be_low']:.0f}-{r['be_high']:.0f}",
                         f"{r['dist_put_sd']:.1f}/{r['dist_call_sd']:.1f}", sp("up", "Y") if r["outside_walls"] else sp("mu", "n"),
                         f"{r['g']['theta']:+,.0f}", f"{r['g']['vega']:+,.0f}", f"{r['g']['delta'] / c['m1']['lot']:+.2f}",
                         both("touch_all", "touch_sim") if "touch_sim" in h_ else both("touch_all", "touch_sim"),
                         both("lose_all", "lose_sim"),
                         f"{h_['lose_lo']:.0f}-{h_['lose_hi']:.0f}%" if "lose_lo" in h_ else "-"])
        hl = next((i for i, r in enumerate(cands) if r is best), None)
        d = table(["Δ", "Strikes (buy/sell)", "Cr pts (premium collected in points)", "Cr/lot", "Max loss", "Breakevens (zero profit at expiry before costs)", "SD put/call", "Walls", "θ/day (estimated daily decay in rupees)", "Vega (value change for a one-point IV rise)", "NetΔ (combined sensitivity to NIFTY)",
                   "Touch all|sim (sold strike reached in all windows | similar VIX windows)", "Lose all|sim (expiry loss in all windows | similar VIX windows)", "Lose 95% range"], rows, hl=hl)
        if best:
            d += (f'<div class="note"><span class="am">★ UNVALIDATED ILLUSTRATION (not an order or approval)</span> {best["lots"]} lot(s) | book at ₹{best["credit_rs"] * c["pt"]:,.0f}/lot | '
                  f'stop at ₹{best["credit_rs"] * c["sm"]:,.0f}/lot loss | adjust if Nifty &gt; {best["sell_call"] - ts["atr"] * c["adj"]:,.0f} or &lt; {best["sell_put"] + ts["atr"] * c["adj"]:,.0f} '
                  f'(rules and size set in config.py)</div>')
        d += f'<div class="note">First row has lowest observed touch frequency among screened candidates (similar VIX when available), then lowest historical loss frequency and gross maximum loss. Touch = high/low reached a short strike in past windows of the same length; Lose = closed beyond a breakeven; sim = only when VIX was within 20% of today. Windows overlap: about {c['eff_samples']} independent windows in 3 years (the 95% range uses that count, a rough guide only). Descriptive only, not a probability of profit. No costs, slippage or adjustments. Greeks: delta per 1 index point, theta per calendar day, vega per 1 vol point, all in ₹ per lot.</div>'
    else:
        d = '<span class="mu">no priced candidates</span>'
    P.append(panel(f"Additional delta-based condor examples {c['e1']:%d %b}  lot {m1['lot']}  (research candidates, not recommendations)", d, True))

    # ---------- history + events
    lg = c["log8"]
    P.append(panel("LAST REPORTS", table(
        ["Date", "Nifty", "VIX", "PCR", "Put/Call wall", "Max pain", "IC", "CAL", "DIR", "FII %L"],
        [[i, n0(r.spot), f"{r.vix:.1f}", n2(r.pcr_oi), f"{n0(r.put_wall)}/{n0(r.call_wall)}", n0(r.max_pain), f"{r.ic_score:.0f}", f"{r.cal_score:.0f}",
          sp(cls(r.bias_score + (r.smart_score if r.smart_score == r.smart_score else 0)), f"{r.bias_score + (r.smart_score if r.smart_score == r.smart_score else 0):+.0f}"),
          n0(r.fii_fut_long_pct) if "fii_fut_long_pct" in r.index else "-"] for i, r in lg.iloc[::-1].iterrows()]), True))
    if c["events"]:
        P.append(panel("EVENTS", "<ul>" + "".join(f"<li>{E(x)}</li>" for x in c["events"]) + "</ul>"))

    stale = sp("dn", f"STALE {c['age_days']}d") if c["age_days"] >= 2 else ""
    warn = f'<div class="warn">{E(" ".join(c["warnings"]))}</div>' if c["warnings"] else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f'<title>NIFTY OPTIONS {day:%d %b %Y}</title><style>{CSS}</style></head><body>'
            f'<div class="top"><h1>NIFTY OPTIONS TERMINAL</h1><span>AS OF {day:%a %d %b %Y} {stale}  built {c["generated"]}  RESEARCH ONLY  EOD settlement prices, not executable quotes</span></div>'
            f'{warn}<div class="tick">{tick}</div><div class="grid">{"".join(P)}</div></body></html>')
