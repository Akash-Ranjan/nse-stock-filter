# NSE Stock Filter

Automatically screens NSE stocks every weekday at **10:15 AM IST** using a three-stage pipeline:

```
FII/DII bought yesterday  →  Volume surging (day candle)  →  Hourly candles bullish
```

---

## How it works

| Stage | What it checks | Data source |
|-------|---------------|-------------|
| **1. FII/DII scan** | Bulk & block deal records from NSE for the previous trading day. Flags symbols where net institutional buying > 0. | NSE `/api/bulk-deals`, `/api/block-deals` |
| **2. Volume surge** | Yesterday's daily volume ≥ 1.5× the average of the prior 3 days. | Yahoo Finance (daily, `.NS`) |
| **3. Hourly bullishness** | ≥ 60 % of the last 3 completed hourly candles are green **and** the most-recent candle closes above its open. | Yahoo Finance (1 h, `.NS`) |

Only stocks that pass **all three** stages are reported.

---

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Run once right now (testing / manual trigger)
```bash
python main.py --now
```

### Run for a specific past date
```bash
python main.py --now --date 2024-05-10
```

### Start the scheduler (fires every weekday at 10:15 AM IST)
```bash
python main.py
```

---

## Output

Results are printed to the terminal in a formatted table and also saved as JSON files in the `output/` directory:

```
output/
└── 20240510_1015_filtered_stocks.json
```

Sample JSON:
```json
{
  "run_at": "2024-05-10T10:15:01+05:30",
  "total_passed": 2,
  "stocks": [
    {
      "symbol": "RELIANCE",
      "fii_dii_bought_yesterday": true,
      "volume": {
        "yesterday_vol": 12500000,
        "avg_vol": 7200000,
        "ratio": 1.74,
        "threshold": 1.5,
        "passed": true
      },
      "hourly_candle": {
        "candles_checked": 3,
        "green_candles": 3,
        "bullish_ratio": 1.0,
        "last_close_above_open": true,
        "drift_up": true,
        "last_close": 2940.5,
        "passed": true
      }
    }
  ]
}
```

---

## Configuration (`config.py`)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SCHEDULE_HOUR / MINUTE` | `10 / 15` | Cron schedule in IST |
| `VOLUME_LOOKBACK_DAYS` | `3` | Days used for baseline volume average |
| `VOLUME_MULTIPLIER` | `1.5` | Minimum ratio of yesterday's vol to baseline |
| `HOURLY_CANDLES_TO_CHECK` | `3` | Recent hourly candles inspected |
| `BULLISH_CANDLE_MIN_RATIO` | `0.60` | Fraction of candles that must be green |
| `FII_DII_KEYWORDS` | *(list)* | Keywords to identify institutional entities |

---

## Project structure

```
stock-filter/
├── main.py                 # Entry point & APScheduler
├── config.py               # All thresholds & settings
├── requirements.txt
├── README.md
└── src/
    ├── nse_client.py       # NSE HTTP session (cookie handling, retries)
    ├── fii_dii_scanner.py  # Bulk/block deal parser + FII/DII detection
    ├── volume_analyzer.py  # Daily volume surge check
    ├── candle_analyzer.py  # Hourly bullishness check
    ├── stock_filter.py     # Pipeline orchestrator
    └── reporter.py         # Terminal output + JSON persistence
```

---

## Notes

- **NSE anti-bot protection**: The client hits the NSE homepage first to obtain session cookies, mimicking a real browser.  If NSE changes its cookie scheme, re-initialise by restarting the script.
- **Holiday handling**: The previous-day logic skips weekends but does **not** account for NSE trading holidays.  On a post-holiday morning, adjust with `--date`.
- **Rate limiting**: A 0.3-second sleep is inserted between yfinance calls to avoid hitting Yahoo Finance rate limits.
- **FII/DII identification**: Bulk deals do not have an explicit `clientType` field in the public API. Identification relies on keyword matching against `FII_DII_KEYWORDS` in `config.py`.  Add known fund names there for better coverage.
