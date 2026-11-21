"""Downloads end-of-day data and keeps your own history in the repo.

Sources
  * NSE F&O bhavcopy (UDiFF format)  -> option chain, OI, futures
  * NSE participant-wise OI file     -> FII / DII / Pro / Client positions (optional)
  * Yahoo Finance (^NSEI, ^INDIAVIX) -> daily Nifty and VIX history
  * NSE index close file             -> backup for today's Nifty / VIX values
Everything fetched is saved under data/, so every day's report can be rebuilt later.
"""
import datetime as dt
import io
import json
import re
import os
from tempfile import NamedTemporaryFile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .config import STRIKE_STEP, UNDERLYING_DISPERSION_HARD

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HIST_FILE = DATA / "history" / "nifty_vix_daily.csv"

PROJECT = ROOT

def configure_storage(mode):
    global ROOT, DATA, HIST_FILE, PART_FILE, CASH_FILE
    ROOT = PROJECT if mode == "exchange" else PROJECT / "runs" / mode
    # Old versions mixed demo and live history. Never inherit an unverified store.
    DATA = ROOT / "data" / "verified_v1"
    HIST_FILE = DATA / "history" / "nifty_vix_daily.csv"
    PART_FILE = DATA / "history" / "participants.csv"
    CASH_FILE = DATA / "history" / "fii_dii_cash.csv"
    for directory in (HIST_FILE.parent, DATA / "snapshots", ROOT / "docs", ROOT / "reports"):
        directory.mkdir(parents=True, exist_ok=True)


def atomic_write(path, writer):
    with NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        name = Path(temp.name)
    try:
        writer(name)
        os.replace(name, path)
    finally:
        name.unlink(missing_ok=True)


def load_master(day, sess, path=None):
    if path is None:
        response = sess.get(f"https://nsearchives.nseindia.com/content/fo/NSE_FO_contract_{day:%d%m%Y}.csv.gz", timeout=45)
        response.raise_for_status()
        path = io.BytesIO(response.content)
    cols = ["TckrSymb", "FinInstrmNm", "FinInstrmId", "XpryDt", "StrkPric",
            "OptnTp", "NewBrdLotQty", "StockNm"]
    master = pd.read_csv(path, compression="gzip", usecols=cols)
    master = master[(master.TckrSymb == "NIFTY") & master.FinInstrmNm.isin(["OPTIDX", "FUTIDX"])].copy()
    master["XpryDt"] = pd.to_datetime(master.XpryDt, unit="s", origin="1980-01-01").dt.normalize()
    master["StrkPric"] /= 100.
    return master


def verify_master(master, opts, futs):
    keys = ["FinInstrmId", "XpryDt", "StrkPric", "OptnTp", "NewBrdLotQty"]
    for frame, kind in [(opts, "OPTIDX"), (futs, "FUTIDX")]:
        fields = keys if kind == "OPTIDX" else ["FinInstrmId", "XpryDt", "NewBrdLotQty"]
        valid = pd.MultiIndex.from_frame(master.loc[master.FinInstrmNm == kind, fields])
        if not pd.MultiIndex.from_frame(frame[fields]).isin(valid).all():
            raise ValueError(f"{kind} bhavcopy contracts disagree with the dated NSE contract master")
    options = master[master.FinInstrmNm == "OPTIDX"]
    monthly = options.StockNm.str.match(r"^NIFTY[0-9]{2}[A-Z]{3}[0-9]", na=False)
    classes = pd.DataFrame({"expiry": options.XpryDt, "monthly": monthly}).drop_duplicates()
    if classes.expiry.duplicated().any():
        raise ValueError("Inconsistent weekly/monthly contract names in NSE master")
    return set(classes.expiry), set(classes.loc[classes.monthly, "expiry"])


HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def nse_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    try:  # visiting the home page first gives the cookies NSE expects
        s.get("https://www.nseindia.com", timeout=15)
    except Exception:
        pass
    return s


# ---------------------------------------------------------------- F&O bhavcopy
def fetch_fo_bhavcopy(day, session):
    url = ("https://nsearchives.nseindia.com/content/fo/"
           f"BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip")
    for _ in range(2):
        try:
            r = session.get(url, timeout=45)
            if r.status_code == 200 and len(r.content) > 1000:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return pd.read_csv(z.open(z.namelist()[0]))
        except Exception:
            pass
    return None


def find_latest_bhavcopy(session, start=None, max_back=10):
    """Walk back from today until a bhavcopy exists (handles weekends and holidays)."""
    day = start or dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    for _ in range(max_back):
        if day.weekday() < 5:
            raw = fetch_fo_bhavcopy(day, session)
            if raw is not None:
                return day, raw
        day -= dt.timedelta(days=1)
    return None, None


REQUIRED = ["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "ClsPric", "PrvsClsgPric",
            "UndrlygPric", "SttlmPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty"]


def prepare_nifty(raw):
    """Keep only NIFTY index options and futures, with clean column types. Raises ValueError on bad data."""
    df = raw.copy()
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"NSE file layout changed; missing columns: {', '.join(missing)}")
    df = df[df["TckrSymb"].astype(str).str.strip() == "NIFTY"].copy()
    df["XpryDt"] = pd.to_datetime(df["XpryDt"]).dt.normalize()
    df["TradDt"] = pd.to_datetime(df["TradDt"]).dt.normalize()
    num = ["StrkPric", "OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric", "PrvsClsgPric",
           "UndrlygPric", "SttlmPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol",
           "NewBrdLotQty"]
    for c in num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["OptnTp"] = df["OptnTp"].astype(str).str.strip()
    opts = df[df["FinInstrmTp"].astype(str).str.strip() == "IDO"].copy()
    futs = df[df["FinInstrmTp"].astype(str).str.strip() == "IDF"].copy()
    if len(opts):
        both = pd.concat([opts, futs])
        if both["TradDt"].nunique() != 1:
            raise ValueError(f"file mixes trade dates: {sorted(d.strftime('%Y-%m-%d') for d in both['TradDt'].unique())}")
        numeric = [c for c in ("StrkPric", "OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric", "PrvsClsgPric", "UndrlygPric",
                               "SttlmPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty") if c in both.columns]
        if np.isinf(both[numeric].to_numpy(dtype=float)).any():
            raise ValueError("infinite values found in numeric fields")
        core_o = ["StrkPric", "UndrlygPric", "SttlmPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty"]
        bad = [c for c in core_o if opts[c].isna().any()]
        if bad:
            raise ValueError(f"missing or unreadable values in option fields: {', '.join(bad)}")
        if len(futs) == 0:
            raise ValueError("no NIFTY futures rows in the file")
        core_f = ["SttlmPric", "UndrlygPric", "OpnIntrst", "ChngInOpnIntrst", "PrvsClsgPric", "NewBrdLotQty"]
        badf = [c for c in core_f if futs[c].isna().any()]
        if badf:
            raise ValueError(f"missing or unreadable values in futures fields: {', '.join(badf)}")
        dup = int(opts.duplicated(["XpryDt", "StrkPric", "OptnTp"]).sum())
        if dup:
            raise ValueError(f"{dup} duplicate NIFTY option rows (same expiry, strike, type); refusing to continue")
        if futs.duplicated(["XpryDt"]).any():
            raise ValueError("duplicate NIFTY futures rows for the same expiry")
        for col in ("OpnIntrst", "TtlTradgVol"):
            if (opts[col] < 0).any():
                raise ValueError(f"negative values in {col}")
        if (futs["OpnIntrst"] < 0).any() or (futs["SttlmPric"] <= 0).any():
            raise ValueError("futures rows have negative OI or non-positive settlement price")
        for col in ("SttlmPric", "ClsPric", "PrvsClsgPric"):
            v = opts[col].dropna()
            if (v < 0).any():
                raise ValueError(f"negative values in {col}")
        if (opts["StrkPric"] <= 0).any() or (both["UndrlygPric"] <= 0).any():
            raise ValueError("non-positive strike or underlying price")
        ud = both["UndrlygPric"]
        if (ud.max() - ud.min()) / ud.median() * 100 > UNDERLYING_DISPERSION_HARD:
            raise ValueError(f"Nifty mark differs across contracts in one file ({ud.min():,.1f} to {ud.max():,.1f})")
        if ((opts["OpnIntrst"] - opts["ChngInOpnIntrst"]) < 0).any():
            raise ValueError("OI change is larger than the OI itself (previous OI would be negative)")
        for e, g in both.groupby("XpryDt"):
            lots = g["NewBrdLotQty"].unique()
            if len(lots) != 1 or not (lots[0] > 0) or lots[0] != int(lots[0]):
                raise ValueError(f"invalid or mixed lot sizes for expiry {e:%d %b %Y}: {[float(x) for x in lots]}")
    return opts, futs


def save_snapshot(opts, futs, day):
    """Save complete strike coverage, including contracts outside the old spot window."""
    out = pd.concat([opts, futs]).assign(snapshot_coverage="full")
    path = DATA / "snapshots" / f"nifty_fo_{day:%Y-%m-%d}.csv.gz"
    atomic_write(path, lambda tmp: out.to_csv(tmp, index=False, compression="gzip"))
    return path


# ---------------------------------------------------------------- participant OI
def parse_participant_text(text, day=None):
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().lower().startswith("client type"))
    if day is not None:
        stamp = re.search(r"as on\s+([A-Za-z]+ \d{1,2}, \d{4})", " ".join(lines[:start]), re.I)
        if stamp is None or pd.Timestamp(stamp[1]).date() != day:
            raise ValueError("Participant file date mismatch")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df.columns = [c.strip() for c in df.columns]
    df["Client Type"] = df["Client Type"].astype(str).str.strip()
    return df


def fetch_participant_oi(day, session):
    """FII / DII / Pro / Client open interest. Optional: returns None on any problem."""
    url = f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv"
    try:
        r = session.get(url, timeout=30)
        return parse_participant_text(r.text, day) if r.status_code == 200 else None
    except Exception:
        return None


def summarise_participants(df):
    """Pull the numbers that matter for an index-options trader (column names matched loosely)."""
    if df is None:
        return None
    low = {c.lower().strip(): c for c in df.columns}
    out = {}
    for who in ["FII", "DII", "Pro", "Client"]:
        row = df[df["Client Type"].str.upper() == who.upper()]
        if row.empty:
            continue
        r = row.iloc[0]
        g = lambda name: float(r[low[name.lower()]]) if name.lower() in low else np.nan
        fl, fs = g("Future Index Long"), g("Future Index Short")
        out[who] = dict(
            fut_long=fl, fut_short=fs, fut_net=fl - fs,
            fut_long_pct=100 * fl / (fl + fs) if (fl + fs) else np.nan,
            call_long=g("Option Index Call Long"), call_short=g("Option Index Call Short"),
            put_long=g("Option Index Put Long"), put_short=g("Option Index Put Short"),
        )
    return out or None


PART_FILE = DATA / "history" / "participants.csv"


def load_participants_log():
    if PART_FILE.exists():
        return pd.read_csv(PART_FILE, index_col="date", dtype={"date": str})
    return pd.DataFrame(index=pd.Index([], dtype=str, name="date"))


def append_participants(day, part):
    if not part or "FII" not in part:
        return
    f = part["FII"]
    row = {"FII_fut_net": f["fut_net"], "FII_fut_long_pct": f["fut_long_pct"],
           "FII_opt_bias": (f["call_long"] - f["call_short"]) - (f["put_long"] - f["put_short"])}
    for who, p in part.items():
        row[f"{who}_fut_net"] = p["fut_net"]
    key = f"{day:%Y-%m-%d}"
    log = load_participants_log()
    new = pd.DataFrame([row], index=pd.Index([key], name="date"))
    merged = pd.concat([log[log.index != key], new]).sort_index()
    atomic_write(PART_FILE, merged.to_csv)


# ---------------------------------------------------------------- FII / DII cash flows
CASH_FILE = DATA / "history" / "fii_dii_cash.csv"


def parse_cash_rows(rows):
    out = {}
    num = lambda x: float(str(x).replace(",", ""))
    for x in rows:
        cat = str(x.get("category", "")).upper()
        who = "FII" if ("FII" in cat or "FPI" in cat) else ("DII" if "DII" in cat else None)
        if who:
            if who in out:
                raise ValueError("Duplicate cash category")
            out[who] = dict(date=pd.to_datetime(x["date"], format="%d-%b-%Y"),
                            buy=num(x["buyValue"]), sell=num(x["sellValue"]), net=num(x["netValue"]))
    for row in out.values():
        buy, sell, net = row["buy"], row["sell"], row["net"]
        if not np.isfinite([buy, sell, net]).all() or min(buy, sell) < 0 or abs(buy - sell - net) > 0.021:
            raise ValueError("Cash buy/sell/net do not reconcile")
    if out and ("FII" not in out or len({r["date"] for r in out.values()}) != 1):
        raise ValueError("Incomplete or misaligned cash dates")
    return out or None


def cash_window(log, day, sessions, holidays, observed_sessions=()):
    if log.empty:
        return None
    dates = pd.bdate_range(end=day, periods=sessions, freq="C", holidays=holidays)
    # Retain any extra observed trading sessions, including weekend special sessions.
    extra = pd.DatetimeIndex(observed_sessions)
    dates = dates.union(extra[(extra >= dates[0]) & (extra <= pd.Timestamp(day))]).sort_values()[-sessions:]
    if dates[-1].date() != day:
        return None
    values = log.reindex(dates.strftime("%Y-%m-%d"))[["fii_buy", "fii_sell", "fii_net"]]
    if not np.isfinite(values.to_numpy()).all():
        return None
    if ((values.fii_buy - values.fii_sell - values.fii_net).abs() > .021).any():
        return None
    return float(values.fii_net.sum())


def fetch_fii_dii_cash(session):
    """Latest FII/DII cash-market numbers (rupees crore). Optional: None on any problem."""
    try:
        r = session.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=20,
                        headers={"Accept": "application/json"})
        return parse_cash_rows(r.json()) if r.status_code == 200 else None
    except Exception:
        return None


def merged_cash(cash):
    log = load_cash_log()
    if not cash or "FII" not in cash:
        return log
    key = f"{cash['FII']['date']:%Y-%m-%d}"
    row = {"fii_buy": cash["FII"]["buy"], "fii_sell": cash["FII"]["sell"], "fii_net": cash["FII"]["net"]}
    if "DII" in cash:
        row.update(dii_buy=cash["DII"]["buy"], dii_sell=cash["DII"]["sell"], dii_net=cash["DII"]["net"])
    new = pd.DataFrame([row], index=pd.Index([key], name="date"))
    return pd.concat([log[log.index != key], new]).sort_index()


def load_cash_log():
    if CASH_FILE.exists():
        return pd.read_csv(CASH_FILE, index_col="date", dtype={"date": str})
    return pd.DataFrame(index=pd.Index([], dtype=str, name="date"))


# ---------------------------------------------------------------- older snapshots
def load_old_snapshot(day, sessions_back=3):
    files = sorted((DATA / "snapshots").glob("nifty_fo_*.csv.gz"))
    files = [f for f in files if f.name < f"nifty_fo_{day:%Y-%m-%d}.csv.gz"]
    if len(files) < sessions_back:
        return None, None
    f = files[-sessions_back]
    df = pd.read_csv(f, parse_dates=["XpryDt", "TradDt"])
    options = df[df["FinInstrmTp"] == "IDO"].copy()
    options.attrs["full_coverage"] = "snapshot_coverage" in df and df.snapshot_coverage.eq("full").all()
    return options, f.name[9:19]


# ---------------------------------------------------------------- price history
def _yahoo_history():
    import yfinance as yf
    frames = {}
    for sym, name in [("^NSEI", "n"), ("^INDIAVIX", "vix")]:
        h = yf.Ticker(sym).history(period="3y", interval="1d", auto_adjust=False)
        if h is None or h.empty:
            raise RuntimeError(f"No Yahoo data for {sym}")
        h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
        frames[name] = h
    n, v = frames["n"], frames["vix"]
    df = pd.DataFrame({
        "n_open": n["Open"], "n_high": n["High"], "n_low": n["Low"], "n_close": n["Close"],
        "vix": v["Close"],
    })
    df.index.name = "date"
    return df.dropna(subset=["n_close"])


def _nse_index_close(day, session):
    """Backup: NSE's own end-of-day index file (has Nifty 50 and India VIX)."""
    url = f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{day:%d%m%Y}.csv"
    try:
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip().lower() for c in df.columns]
        name = df.columns[0]
        pick = lambda label, col: float(df.loc[df[name].str.strip().str.lower() == label,
                                               [c for c in df.columns if col in c][0]].iloc[0])
        return dict(
            n_open=pick("nifty 50", "open"), n_high=pick("nifty 50", "high"),
            n_low=pick("nifty 50", "low"), n_close=pick("nifty 50", "closing"),
            vix=pick("india vix", "closing"),
        )
    except Exception:
        return None


def update_history(day, session, bhav_spot, warnings, hist_override=None):
    """Merge Yahoo data into our own CSV, then make sure `day` is present."""
    old = None
    if HIST_FILE.exists():
        old = pd.read_csv(HIST_FILE, parse_dates=["date"], index_col="date")
    if hist_override is not None:
        new = pd.read_csv(hist_override, parse_dates=["date"], index_col="date")
    else:
        try:
            new = _yahoo_history()
        except Exception as e:
            new = None
            warnings.append(f"Yahoo history failed ({e}); using saved history.")
    hist = new if old is None else (old if new is None else new.combine_first(old))
    if hist is None:
        raise RuntimeError("No price history available (Yahoo failed and no saved file).")
    hist = hist.sort_index()
    ts = pd.Timestamp(day)
    if ts not in hist.index or pd.isna(hist.loc[ts, "vix"]):
        extra = _nse_index_close(day, session)
        if extra:
            hist.loc[ts, list(extra)] = list(extra.values())
            warnings.append("Today's Nifty/VIX taken from the NSE index file (Yahoo was behind).")
        elif ts not in hist.index and bhav_spot:
            hist.loc[ts, ["n_open", "n_high", "n_low", "n_close"]] = bhav_spot
            warnings.append("Today's Nifty candle approximated from F&O file (high/low unknown).")
    return hist


# ---------------------------------------------------------------- own daily log
def load_metrics_log():
    p = DATA / "history" / "daily_metrics.csv"
    if p.exists():
        return pd.read_csv(p, index_col="date", dtype={"date": str})
    return pd.DataFrame(index=pd.Index([], dtype=str, name="date"))


def merged_metrics(day, row):
    log = load_metrics_log()
    key = f"{day:%Y-%m-%d}"
    new = pd.DataFrame([row], index=pd.Index([key], name="date"))
    return pd.concat([log[log.index != key], new]).sort_index()


def load_events():
    p = PROJECT / "data" / "events.csv"
    try:
        ev = pd.read_csv(p, parse_dates=["date"])
        if not {"date", "event", "impact"}.issubset(ev) or ev[["date", "event"]].isna().any().any():
            raise ValueError("Incomplete events file")
        ev["date"] = pd.to_datetime(ev.date)
        ev.attrs["read_ok"] = True
        return ev
    except Exception:
        return pd.DataFrame(columns=["date", "event", "impact"])


def event_coverage(events, day, expiry):
    try:
        coverage = json.loads((PROJECT / "data" / "event_coverage.json").read_text())
        return (bool(events.attrs.get("read_ok")) and bool(coverage["source"].strip())
                and pd.Timestamp(coverage["as_of"]).date() <= day
                and pd.Timestamp(coverage["from"]).date() <= day
                and pd.Timestamp(coverage["through"]) >= expiry)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
