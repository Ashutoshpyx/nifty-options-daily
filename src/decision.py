"""Research screen. All valuation is at the front expiry, before costs."""
import numpy as np
from scipy.special import ndtr
from .advanced import leg_greeks
from .analysis import vertical
from .config import IC_WINGS, RISK_FREE


def interval(w, vix, spot):
    if not w:
        return None
    match = np.abs(w["vix"]/vix - 1) <= .20
    if match.sum() < 30:
        return None
    return {k: spot*(1 + sign*w[k][match]) for k, sign in
            (("end", 1), ("up", 1), ("dn", -1))}


def range_validation(week):
    """Walk forward in five-session steps, admitting only fully realised past labels."""
    if not week: return None
    covered = []
    for i in range(252, len(week["end"]), 5):
        stop = i-4
        past = week["end"][:stop][abs(week["vix"][:stop]/week["vix"][i]-1)<=.20]
        if len(past)>=30:
            lo,hi=np.percentile(past,[10,90])
            covered.append(lo<=week["end"][i]<=hi)
    return (float(np.mean(covered)),len(covered)) if covered else None


def review(near, far, front, back, m, vs, ts, outlook, windows, week, events):
    s, lot, sd = m["spot"], m["lot"], m["sd_move"]
    sample = interval(windows, vs["vix"], s)
    weekly = interval(week, vs["vix"], s)
    result = dict(picks={}, reasons=[], total=0, chosen=None, week=None, validation=range_validation(week))
    if weekly:
        result["week"] = [*np.percentile(weekly["end"], [10,50,90]), len(weekly["end"])]
    if events is None or events:
        result["reasons"].append("Event coverage is unverified or a scheduled event falls before expiry.")
    if sample is None or outlook == "Insufficient data":
        result["reasons"].append("Insufficient market or historical coverage.")
        return result
    end, high, low = [sample[k] for k in ("end","up","dn")]
    q = .90 if vs["pctile"] >= 75 or vs["chg5_pct"] >= 10 else .80
    down = max(sd, s-np.quantile(low,1-q))
    up = max(sd, np.quantile(high,q)-s)
    bullish = "bullish" in outlook.lower()
    bearish = "bearish" in outlook.lower()
    if bullish: up = max(up,down) + .25*ts["atr"]
    if bearish: down = max(up,down) + .25*ts["atr"]
    strong = outlook in ("Bullish","Bearish")
    sides = ["PE"] if strong and bullish else ["CE"] if strong else ["PE","CE"]
    # Separate per-strike tables avoid repricing a leg for each possible partner.
    prices = {}
    calendars = {}
    for kind in sides:
        sign = 1 if kind == "CE" else -1
        distance = up if sign==1 else down
        col = kind.lower()
        ks = [k for k in near.index if distance <= sign*(k-s) <= distance+sd
              and near.at[k,col+"_vol"]>0 and near.at[k,col+"_oi"]>0 and near.at[k,col+"_px"]>0]
        prices[kind] = ks
        calendars[kind] = {}
        for k in ks:
            if k not in far.index or lot!=back["lot"] or far.at[k,col+"_vol"]<=0: continue
            iv, n, f = far.at[k,col+"_iv"],near.at[k,col+"_px"],far.at[k,col+"_px"]
            niv = near.at[k,col+"_iv"]
            if not np.isfinite([iv,niv,f]).all() or min(iv,niv,f)<=0: continue
            qty = 1 if strong else 2
            t = back["Tm"]-front["Tm"]
            if t<=0: continue
            # Include a wide gap on either side in the reported stress loss.
            spots = np.r_[end,s,s*.90,s*1.10]
            F = spots*np.exp(RISK_FREE*t)
            def payoff(vol):
                v=max(vol,.01)*np.sqrt(t)
                d=np.log(F/k)/v+v/2
                remaining=np.exp(-RISK_FREE*t)*sign*(F*ndtr(sign*d)-k*ndtr(sign*(d-v)))
                return (remaining-qty*np.maximum(sign*(spots-k),0)+qty*n-f)*lot
            theta = lot*(leg_greeks(far,back,k,kind)["theta"] - qty*leg_greeks(near,front,k,kind)["theta"])
            calendars[kind][k]=(payoff(iv),payoff(iv-.03), (qty*n-f)*lot,niv-iv,theta)
    def record(name, legs, net, pnl, stress, touch, strikes, cap, gain, gap=0, scenario=None):
        result["total"]+=1
        row=dict(name=name,legs=legs,net=net,median=np.median(pnl),touch=touch.mean(),
                 stress=stress,win=(pnl>0).mean(),loss=cap,profit=gain,gap=gap,count=len(end),scenario=scenario)
        # Prefer positive typical outcomes, then fewer touches and smaller stress losses.
        oi_floor=min(near.at[k,side.lower()+"_oi"] for side,k in zip(sides,strikes))
        key=(row["median"]<=0,row["touch"],-stress,-row["median"],-oi_floor)
        if name not in result["picks"] or key<result["picks"][name][0]:
            result["picks"][name]=(key,row)
    from itertools import product
    for strikes in product(*(prices[k] for k in sides)):
        bounds=dict(zip(sides,strikes))
        p,c=bounds.get("PE"),bounds.get("CE")
        if bullish and c and p and c-s <= s-p: continue
        if bearish and c and p and s-p <= c-s: continue
        hit=np.zeros(len(end),dtype=bool)
        if p: hit |= low<=p
        if c: hit |= high>=c
        if not strong:
            for width in IC_WINGS:
                a=vertical(near,"PE",p-width,p,lot)
                b=vertical(near,"CE",c+width,c,lot)
                if not a or not b: continue
                credit=a["net"]+b["net"]
                loss=(width-credit)*lot
                if loss<=0 or credit*lot<.15*loss: continue
                pnl=(credit-np.clip(p-end,0,width)-np.clip(end-c,0,width))*lot
                record("Iron condor",f"Front expiry: buy 1 × {p-width:g} PE, sell 1 × {p:g} PE, sell 1 × {c:g} CE, buy 1 × {c+width:g} CE",credit*lot,pnl,-loss,hit,strikes,loss,credit*lot)
        if any(k not in calendars[side] for side,k in bounds.items()): continue
        legs=[calendars[side][k] for side,k in bounds.items()]
        if sum(x[4] for x in legs)<=0: continue
        pnl=sum(x[0] for x in legs)
        shock=sum(x[1] for x in legs)
        net=sum(x[2] for x in legs)
        label="Single put calendar" if strong and p else "Single call calendar" if strong else "2:1 double calendar"
        desc=", ".join(f"{k:g} {side}" for side,k in bounds.items())
        record(label,f"Sell {1 if strong else 2} front lot(s) each of {desc}. Buy 1 next-expiry lot each at identical strikes.",net,pnl[:-3],min(pnl.min(),shock.min()),hit,strikes,None,None,np.mean([x[3] for x in legs]),[pnl[-3:],shock[-3:]])
    result["picks"]={k:v[1] for k,v in result["picks"].items()}
    picks=result["picks"]
    if strong: choice=next(iter(picks),None)
    else:
        cal=picks.get("2:1 double calendar")
        favourable=cal and vs["pctile"]<=40 and vs["chg5_pct"]<10 and cal["gap"]>=-.01 and cal["median"]>0
        choice="2:1 double calendar" if favourable else "Iron condor" if "Iron condor" in picks else None
    result["chosen"]=choice
    if not choice or picks[choice]["median"]<=0:
        result["reasons"].append("No eligible structure with a positive median gross scenario under the selection rules.")
    if choice=="2:1 double calendar":
        result["reasons"].append("Extra short lots have uncapped call-side loss. Review only under the capital-preservation rule.")
    return result
