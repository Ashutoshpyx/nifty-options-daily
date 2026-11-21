"""All the numbers you may want to tweak live here."""

RISK_FREE = 0.065          # used only to turn option prices into implied volatility
STRIKE_STEP = 50           # Nifty strike gap
LOT_FALLBACK = 65          # Nifty lot size since Jan 2026 contracts; used only if the file lacks it

# VIX regimes (upper limit, label)
VIX_BANDS = [(12, "very low"), (15, "low"), (20, "normal"), (25, "high"), (1e9, "very high")]

# Iron condor candidates: short-strike deltas and wing widths (points)
IC_DELTAS = [0.10, 0.15, 0.20]
IC_WINGS = [100, 200]

# Calendar spread strikes, in points away from ATM
CAL_OFFSETS = [-200, -100, 0, 100, 200]

# Vertical (directional) spread width in points
VERT_WIDTH = 100

# Scorecard thresholds
T = dict(
    ic_vix_pct_min=40,        # VIX percentile (1y) at least this for selling premium
    ic_adx_max=25,            # trend strength below this = not strongly trending
    ic_pcr_low=0.8, ic_pcr_high=1.3,
    ic_vix_5d_rise_max=10.0,  # percent rise of VIX in 5 days considered dangerous
    ic_wall_width_min=1.0,    # (call wall - put wall) / 1-SD move to expiry
    cal_vix_pct_max=50,
    cal_adx_max=22,
    cal_term_gap_min=-1.0,    # near IV minus far IV (vol points) must be at least this
    cal_pin_pct=0.5,          # spot within this percent of max pain
    bias_bull=3, bias_bear=-3,
)

# ---- Trade planning (EDIT THESE to your own numbers)
CAPITAL = 1_000_000        # trading capital in rupees, used only for lot-size suggestions
RISK_PCT = 1.0             # max loss you accept on one trade, % of capital
PROFIT_TARGET = 0.5        # example rule: book profit at this share of the credit
STOP_MULT = 1.5            # example rule: exit when loss reaches this multiple of the credit
ADJUST_ATR_MULT = 1.0      # example rule: look at adjusting when Nifty is within this many ATRs of a short strike

# Show the illustrative sizing / exit plan and the "lots" column? Off by default: this is a research tool.
SHOW_PLAN = False

# ---- Data-quality gates (the report stops when these are breached)
FUT_TOL_WARN = 0.3          # % gap between Nifty future and option-implied forward: warn
FUT_TOL_HARD = 1.0          # % gap: stop
QUALITY_F_SPREAD_HARD = 1.0 # % disagreement between put-call forwards on one expiry: stop
MIN_TRADED_PAIRS = 3        # near-money strikes where both call and put traded
STRICT_CALENDAR = True      # stop if the trade year is not listed in data/holiday_coverage.json
SPOT_TOL_HARD = 1.0        # % gap between the option file's Nifty mark and the index close: stop
SPOT_TOL_WARN = 0.3
UNDERLYING_DISPERSION_HARD = 0.1   # % spread of the Nifty mark across contracts in one file: stop

NEAR_MONEY_PCT = 1.0  # paired trades within +/-1% of spot
