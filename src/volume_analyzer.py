"""
Volume Analyzer
===============
Checks whether a stock's *previous trading day* volume significantly exceeds
the rolling average of the N days before it.

Data source: NSE's daily bhavcopy (sec_bhavdata_full_DDMMYYYY.csv) from
nsearchives.nseindia.com — no auth, no rate limits, always available after
market close.

Format of the bhavcopy CSV
---------------------------
  SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE,
  LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY (volume), ...
"""
import io
import logging
import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import urllib3

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ARCHIVE_BASE = "https://nsearchives.nseindia.com"
_BHAVCOPY_URL = _ARCHIVE_BASE + "/products/content/sec_bhavdata_full_{date}.csv"

_SESSION = requests.Session()
_SESSION.verify = False
_SESSION.headers["User-Agent"] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _trading_days_before(d: date, n: int) -> List[date]:
    """Return the last *n* weekday dates on or before *d* (newest first)."""
    days = []
    cur = d
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur -= timedelta(days=1)
    return days


def _fetch_bhavcopy(d: date) -> Optional[pd.DataFrame]:
    """Download the bhavcopy for date *d*. Returns None on failure."""
    date_str = d.strftime("%d%m%Y")
    url = _BHAVCOPY_URL.format(date=date_str)
    try:
        resp = _SESSION.get(url, timeout=config.NSE_REQUEST_TIMEOUT)
        if resp.status_code == 404:
            logger.debug("Bhavcopy not found for %s (holiday?)", d)
            return None
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip().upper() for c in df.columns]
        return df
    except Exception as exc:
        logger.warning("Bhavcopy fetch failed for %s: %s", d, exc)
        return None


def _get_volume(d: date, symbol: str) -> Optional[float]:
    """Return the EQ-series volume for *symbol* on trading day *d*."""
    df = _fetch_bhavcopy(d)
    if df is None or df.empty:
        return None
    sym_upper = symbol.strip().upper()
    row = df[(df["SYMBOL"] == sym_upper) & (df["SERIES"].str.strip() == "EQ")]
    if row.empty:
        logger.debug("%s not found in bhavcopy for %s", symbol, d)
        return None
    vol_col = next((c for c in df.columns if "TTL_TRD_QNTY" in c or "VOLUME" in c), None)
    if vol_col is None:
        return None
    return float(row.iloc[0][vol_col])


class VolumeAnalyzer:
    def __init__(
        self,
        lookback_days: int = config.VOLUME_LOOKBACK_DAYS,
        multiplier: float = config.VOLUME_MULTIPLIER,
    ):
        self._lookback = lookback_days
        self._multiplier = multiplier

    def is_volume_surging(self, symbol: str) -> Tuple[bool, Dict]:
        """
        Returns (True, detail_dict) if yesterday's volume ≥ *multiplier* ×
        the average of the prior *lookback_days* trading days.
        """
        # Need lookback + 1 days: yesterday + N baseline days
        days_needed = self._lookback + 1
        candidates = _trading_days_before(date.today() - timedelta(days=1), days_needed + 5)

        volumes: List[Tuple[date, float]] = []
        for d in candidates:
            if len(volumes) >= days_needed:
                break
            vol = _get_volume(d, symbol)
            if vol is not None:
                volumes.append((d, vol))

        if len(volumes) < days_needed:
            logger.debug("%s: only %d volume days found (need %d)", symbol, len(volumes), days_needed)
            return False, {"passed": False, "reason": f"only {len(volumes)} days of data found"}

        # volumes[0] = yesterday (most recent), volumes[1:] = baseline
        yesterday_date, yesterday_vol = volumes[0]
        baseline_vols = [v for _, v in volumes[1:days_needed]]
        avg_vol = sum(baseline_vols) / len(baseline_vols)

        if avg_vol == 0:
            return False, {"passed": False, "reason": "zero average volume"}

        ratio = yesterday_vol / avg_vol
        passed = ratio >= self._multiplier

        detail = {
            "date": yesterday_date.isoformat(),
            "yesterday_vol": int(yesterday_vol),
            "avg_vol": int(avg_vol),
            "ratio": round(ratio, 2),
            "threshold": self._multiplier,
            "passed": passed,
        }
        logger.debug(
            "%s volume → %s vol=%d avg=%d ratio=%.2f passed=%s",
            symbol, yesterday_date, int(yesterday_vol), int(avg_vol), ratio, passed,
        )
        return passed, detail
