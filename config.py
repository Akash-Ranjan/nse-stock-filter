"""
Global configuration for the NSE Stock Filter.
Tune thresholds here without touching business logic.
"""
import pytz

# ---------------------------------------------------------------------------
# Timezone & Schedule
# ---------------------------------------------------------------------------
IST = pytz.timezone("Asia/Kolkata")
SCHEDULE_HOUR = 10
SCHEDULE_MINUTE = 15          # Run every day at 10:15 AM IST

# ---------------------------------------------------------------------------
# Volume Filter
# ---------------------------------------------------------------------------
# Number of previous trading days to use as the baseline average
VOLUME_LOOKBACK_DAYS = 3
# Yesterday's volume must be >= this multiple of the baseline average
VOLUME_MULTIPLIER = 1.5

# ---------------------------------------------------------------------------
# Hourly Candle Bullishness
# ---------------------------------------------------------------------------
# How many of the most-recent completed hourly candles to inspect
HOURLY_CANDLES_TO_CHECK = 3
# Fraction of those candles that must be green (close > open) to be "bullish"
BULLISH_CANDLE_MIN_RATIO = 0.60

# ---------------------------------------------------------------------------
# NSE HTTP Client
# ---------------------------------------------------------------------------
NSE_REQUEST_TIMEOUT = 15        # seconds
NSE_RETRY_ATTEMPTS = 3
NSE_RETRY_DELAY = 2             # seconds between retries

# ---------------------------------------------------------------------------
# FII / DII Identification
# ---------------------------------------------------------------------------
# Keywords (case-insensitive) that identify an entity as an FII/DII in
# NSE bulk-deal client names.  Add your own patterns here.
FII_DII_KEYWORDS = [
    "fii", "fpi", "foreign", "portfolio", "overseas",
    "dii", "mutual fund", "insurance", "pension", "provident",
    "lic ", "sbi mf", "hdfc mf", "icici pru", "nippon", "axis mf",
    "kotak mf", "aditya birla", "franklin", "mirae", "invesco",
    "blackrock", "vanguard", "fidelity", "jp morgan", "goldman",
    "morgan stanley", "ubs ", "citigroup", "merrill", "nomura",
    "credit suisse", "deutsche", "societe generale", "baring",
    "templeton", "motilal", "dsp ", "tata mf",
]

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
OUTPUT_DIR = "output"
RESULTS_FILENAME = "filtered_stocks.json"
LOG_LEVEL = "INFO"
