# Nifty options terminal (end-of-day)

One dense, dark, terminal-style page per day for Nifty 50 options. Numbers first, almost no prose.
Built for iron condors, calendar spreads and one-sided calendars, centred on the weekly expiry.

## What is on the page
| Panel | What you get |
|---|---|
| Ticker | Nifty, VIX and percentile, PCR, ATM IV, 1 SD move, OI walls, max pain, FII % long, outlook |
| Signal board | Condor score, calendar score, direction score, and what changed since the last report |
| Checklists | Each condition shown as value, rule and pass/fail; direction shown as ▲▼ signals (technical, OI, futures, FII) |
| Level ladder | Every important level in one list around spot: OI walls, pivots, EMAs, 1 SD, 90% history range, max pain, pin strikes, best condor shorts. ★ = levels agreeing within 40 pts |
| Weekly expiry | Straddle price and decay per day, breakevens, implied vs historical move, how often Nifty touched the 1 SD range in 3 years, history-based levels, expiry comparison |
| Volatility | VIX percentile and IV rank, VIX vs actual movement, premium rank, what VIX did next in similar past conditions |
| Technical | Trend label, ADX, EMAs, RSI, MACD, ATR, Bollinger squeeze, pivots, 52-week range |
| Charts | OI profile with change, Nifty 120d, VIX 1y, IV smile, 3-year distribution of Nifty moves |
| Option chain | 19 strikes with OI bars, OI change, IV, price |
| PCR and OI | PCR by OI, volume, near-money and change; walls, fresh writing and unwinding; 3-session OI build-up; option activity labelled bullish or bearish |
| Futures, FII/DII | Futures build-up and premium; FII, DII, Pro, Client positions; cash flows with 5 and 20 day totals |
| Desks | Iron condor (Greeks, sizing, past touch and loss rates, plan), four-leg double calendars (combined debit, theta, vega, delta and spot/IV scenario P&L), single put or call calendars |
| History | Last 8 reports side by side, upcoming events |

Hover a label on a computer to see a one-line meaning.

## Strike selection and research basis

The main screen uses the nearest unexpired contract and the immediately following expiry. Neutral and mildly directional views compare condors and double calendars. Double calendars sell two lots and buy one per side. For strong bullish or bearish scores, respectively, only same-strike 1:1 put or call calendars are considered. The technical, OI/PCR and positioning score is a heuristic.

Distances start at the larger of expiry implied standard deviation and the historical high/low excursion at similar starting VIX (within 20%, minimum 30 windows). The excursion percentile is 80, rising to 90 for elevated or fast-rising VIX. Mild bullishness adds a quarter ATR on the call side and enforces a strictly farther call. Mild bearishness mirrors it. Search extends one further implied move. Require traded marks, nonzero short OI, matching calendar lots and positive combined calendar theta. Condors use 100/200-point wings and require credit of at least 15% of gross maximum loss. Within each family, rank positive median P&L first, then touch frequency, worst evaluated P&L, median P&L and minimum short-leg OI.

Low VIX alone does not establish value. The double-calendar review additionally requires VIX percentile at most 40, five-session VIX rise below 10%, mean near IV no more than one vol point below far IV and positive median P&L. The residual short call prevents promoting that review to a conservative trade. Unknown events, missing observations, stale data and inadequate scenarios can also produce no trade. These thresholds are design assumptions. The quoted median values use historical spot moves and repriced options before costs. No realised option-strategy alpha has been established.

The next-five-session band uses historical closing moves conditional on VIX. A rolling replay uses only completed windows available at each calculation date and evaluates every fifth origin after a 252-observation warm-up. It validates coverage of the closing range only. NSE defines India VIX over 30 calendar days; weekly IV comes independently from expiry marks. See [NSE India VIX](https://www.nseindia.com/static/products-services/indices-indiavix-index), [OIC put calendars](https://www.optionseducation.org/strategies/all-strategies/long-put-calendar-spread-put-horizontal), and [Cboe term structure](https://www.cboe.com/tradable_products/vix/term_structure). These sources describe instrument mechanics, not validation of the screen.

## First upload and daily dashboard

1. Create an empty GitHub repository named `nifty-options-daily`. Use a public repository if you want Pages with a free GitHub account. Keep account credentials out of the files.
2. Extract this entire ZIP on Windows. From inside the extracted directory, upload the contents to the root of the default branch, including the hidden `.github` directory. GitHub Desktop can commit hidden files: clone the empty repository, copy the extracted contents into the clone, then commit and publish. Check that GitHub shows `.github/workflows/daily_report.yml` and `requirements.txt` at their expected paths.
3. In Settings → Pages → Build and deployment, select **GitHub Actions**.
4. In Actions → Daily Nifty options terminal, choose **Run workflow** on the default branch. Enable Actions if prompted. The workflow needs permission to write history back to that branch.
5. Open the link shown by the **deploy** job. Bookmark it. The latest HTML is also committed to `docs/index.html`, daily archives to `docs/YYYY-MM-DD.html`, and the short brief to `reports/latest.md`.

The scheduled runs are Monday through Friday at 7 PM and 9 PM India time. The second run retries after the exchange files have had more time to appear. On holidays the latest available session may remain on display. Check the report's “AS OF” date. If a quality check or upstream download fails, the last published page stays available. Open the failed step in Actions for the cause. Scheduled times can be delayed by GitHub. Telegram secrets are optional.

## Data (all end-of-day, saved in your repo)
| Data | Source | Saved as |
|---|---|---|
| Option chain, OI, futures | NSE F&O bhavcopy | `data/verified_v1/snapshots/` |
| FII/DII/Pro/Client OI | NSE participant-wise OI | `data/verified_v1/history/participants.csv` |
| FII/DII cash | NSE FII/DII API | `data/verified_v1/history/fii_dii_cash.csv` |
| Nifty and VIX history | Yahoo Finance, NSE index file as backup | `data/verified_v1/history/nifty_vix_daily.csv` |
| Your daily log | computed | `data/verified_v1/history/daily_metrics.csv` |

Cash flow and FII change numbers build up from your first successful run; they cannot be back-filled.
Rebuild any day: `python -m src.build_report --date 2026-11-20 --force`

## Audit corrections and existing installations

Exchange builds fetch the dated NSE contract master, match NIFTY contract IDs, expiry, strike, side and lot, and use its weekly/monthly classes. The selected expiry horizon needs verified holiday coverage. An explicit date is exact. A backfill produces a dated report and preserves a newer latest page and history. The first exchange run starts a fresh history under `data/verified_v1/` because older versions mixed demo and exchange history. Rebuild earlier sessions from exchange sources if historical comparisons are needed.

Both ATM IVs must be finite and positive. Each selected chain requires three traded call/put pairs within 1% of spot by default. Strategy tables omit legs with zero daily volume. End-of-day trading volume does not establish an executable price. An unavailable required input stops publication and leaves the last successful report dated as before.

Local file overrides write under `runs/replay/`. Supply the official gzipped contract file using `--contract-file` for a replay, or the dated master is fetched. Only an exchange build can publish to the regular output folders or send alerts. Demo runs have separate history and a permanent warning in the HTML and brief.

An event score requires a readable `data/events.csv` and `data/event_coverage.json` with string fields `source`, `as_of`, `from` and `through`. Dates use YYYY-MM-DD. Record the actual source and coverage after checking the event list. A missing or unverified calendar earns no point. Cash windows require reconciled FII buy, sell and net values for all expected sessions through the report date.

## If NSE blocks GitHub's servers
NSE sometimes refuses cloud addresses. If the workflow fails with "Could not download", run the same script on your own PC and push the result. Windows Task Scheduler can do this at 7 PM.

## Check on the first real run
* **OI units**: PCR, walls and max pain do not depend on them; the "L" (lakh) figures do.
* **File names and column names** come from NSE's current layouts. If NSE changes them the script stops with a clear message. FII and cash panels are skipped with a note if their files cannot be read.
* **IV is calculated** from option prices (the bhavcopy has no IV column).

## Make it yours
* `src/config.py`: capital, risk per trade, profit and stop rules, adjust distance, VIX bands, delta targets, wing widths, all scorecard thresholds.
* `data/events.csv`: add RBI policy, Fed, budget, big results (`date,event,impact`, date as YYYY-MM-DD). Checklists flag events before expiry.

## Scope: research tool, not a production trading system
Independent reviewers rated this "not approved for live trading, automated sizing or production risk limits". That is the right reading. It is an end-of-day screening and planning aid. By default it shows no position size and no "best trade" (`SHOW_PLAN = False` in `config.py`; turn it on only if you want the illustrative sizing and exit plan). It never places orders.

Data checks added: forwards are built from strikes that actually traded; the report warns when put-call forwards disagree by more than 0.15% or differ from the Nifty future by more than 0.3%; direction signals with missing inputs are left out, and the score is suppressed when fewer than 4 remain; the dependency versions are pinned and the workflow cannot run twice at once.
Hard stops (no report is produced; each is covered by a test): changed NSE file layout, duplicate option rows, more than 10% unreadable prices, a file that mixes trade dates, infinite or missing OI, volume, price or lot fields (options and futures), duplicate futures rows, a Nifty mark that differs between contracts or by more than 1% from the index close, negative OI or volume, negative prices, a zero or mixed lot size inside one expiry, an OI change bigger than the OI, put-call forwards disagreeing by more than 1% or fewer than 3 traded near-money strike pairs on any expiry used, a Nifty future more than 1% away from the option-implied forward, an expiry that falls on a weekend or NSE holiday, a year missing from `data/holiday_coverage.json`, VIX missing for the latest session. Calendars are not shown across expiries with different lot sizes. Contracts expiring today or already expired are not valued. Direction ideas are not shown when there are too few inputs.
Holidays: `data/holidays.csv` holds the 15 weekday holidays of 2026 (NSE circulars NSE/FAOP/71777 and NSE/CMTR/71775, 12 Dec 2025) plus the F&O-only closure on 15 Jan 2026 (NSE/FAOP/72262). Each January, add the new year's official list and add the year to `data/holiday_coverage.json`; until you do, the report stops (set `STRICT_CALENDAR = False` in `config.py` to only warn). The weekly expiry moves to the previous trading day when Tuesday is a holiday (for example Mon 23 Nov 2026), which the data itself shows. List NSE trading holidays in `data/holidays.csv` (`date` column, YYYY-MM-DD) so session counts are right. Expiry day: the nearest expiry is skipped on its own expiry day and the next one is used.
Delta and gamma are shown against the index (spot). The forward-based versions are kept inside the code as `delta_fwd` and `gamma_fwd`. The page header shows the as-of session and how old it is.
Things a production system would need that this does not have: a licensed live feed with bid/ask, out-of-sample backtests of real option positions with costs, portfolio risk limits, and independent model validation.

## Known limits (read before sizing trades)
* **Forward and IV** come from end-of-day settlement prices, which can be stale for illiquid strikes. A live system would use bid/ask mid-prices with liquidity filters.
* **Expected move** (spot x ATM IV x sqrt(time)) is a one-standard-deviation approximation, not a guaranteed range.
* **Past touch / loss rates** use overlapping windows (not independent), scale strikes by percentage distance and ignore costs, slippage and adjustments. They describe history; they are not a probability of profit. The tool no longer shows a "POP" number for this reason.
* **Session count** skips weekends and the holidays listed in `data/holidays.csv`. Exceptional sessions (such as the Sunday Muhurat session) are not modelled, and history before the covered year is only as good as the list.
* **VIX minus trailing vol** is a backward-looking proxy, not a true forward risk premium.
* **Gamma-OI strikes** show where option activity is concentrated. They do not show dealer positioning and are not a price-pin forecast.
* **OI walls, PCR, max pain, FII scores** are descriptive, rule-based signals, not calibrated forecasts.
* **Lot size**: the contract's own lot field in the bhavcopy is used. The fallback in `config.py` is 65 (Nifty from January 2026); NSE revises lot sizes from time to time, so check it. Past days must use their own lot field, not today's fallback.
* Max-loss sizing excludes brokerage, taxes, exchange charges and slippage. Keep a buffer.

Run the calculation tests: `python -m unittest discover -s tests -t . -v`

## Try it without NSE (invented numbers)
    python tests/make_demo_data.py
    python tests/run_demo.py
Open `runs/synthetic/docs/index.html`. The regenerated demo is in `examples/sample_terminal_SYNTHETIC.html`. The separate `examples/NSE_2026-11-20.html` is a dated first-run report from the exchange build.

For study and planning only. Not investment advice. Prices are end-of-day settlement prices; real fills differ.
