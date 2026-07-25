"""
Candle Analyzer
===============
Checks whether a stock's recent hourly candles are bullish.

"Bullish" definition used here
--------------------------------
  • At least BULLISH_CANDLE_MIN_RATIO of the last HOURLY_CANDLES_TO_CHECK
    completed hourly candles are green (close > open).
  • The most-recent candle's close is above its open.

An optional secondary check compares the close of the last candle
to the open of the first in the window to confirm an upward drift.

Data source: Yahoo Finance (1h interval, last 5 days).
"""
import logging
import os
import sys
from typing import Dict, Tuple

# curl_cffi (used by yfinance ≥1.2) reads verify= at Session construction time.
# Patch the default to False so it works on networks with corporate SSL inspection.
try:
    from curl_cffi import requests as _curl_req
    _orig = _curl_req.Session.__init__
    def _patched(self, *a, **kw):
        kw.setdefault("verify", False)
        _orig(self, *a, **kw)
    _curl_req.Session.__init__ = _patched
    _YF_SESSION = _curl_req.Session(verify=False)
except ImportError:
    _YF_SESSION = None

import pandas as pd
import urllib3
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _yf_symbol(nse_symbol: str) -> str:
    s = nse_symbol.strip().upper()
    return s if s.endswith(".NS") else s + ".NS"


def _fetch_hourly_ohlcv(symbol: str) -> pd.DataFrame:
    """Download the last 5 trading days of 1-hour candles.
    Retries on rate-limit errors with exponential backoff.
    """
    import time as _time
    yf_sym = _yf_symbol(symbol)
    kwargs = dict(
        period="5d",
        interval="1h",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if _YF_SESSION is not None:
        kwargs["session"] = _YF_SESSION

    for attempt in range(1, 4):
        try:
            df = yf.download(yf_sym, **kwargs)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df.dropna(subset=["Close", "Open"])
        except Exception as exc:
            msg = str(exc).lower()
            if "rate" in msg or "429" in msg or "too many" in msg:
                wait = 3 * attempt
                logger.warning("Rate limited for %s – retrying in %ds …", symbol, wait)
                _time.sleep(wait)
            else:
                logger.warning("Hourly data fetch failed for %s: %s", symbol, exc)
                return pd.DataFrame()
    logger.warning("Giving up on hourly data for %s after 3 rate-limit retries", symbol)
    return pd.DataFrame()


class CandleAnalyzer:
    def __init__(
        self,
        candles_to_check: int = config.HOURLY_CANDLES_TO_CHECK,
        min_bullish_ratio: float = config.BULLISH_CANDLE_MIN_RATIO,
    ):
        self._n = candles_to_check
        self._min_ratio = min_bullish_ratio

    def is_hourly_bullish(self, symbol: str) -> Tuple[bool, Dict]:
        """
        Returns (True, detail_dict) when the most-recent hourly candles
        satisfy the bullishness criteria.

        detail_dict contains:
            candles_checked, green_candles, bullish_ratio, last_close_above_open, passed
        """
        df = _fetch_hourly_ohlcv(symbol)

        if df.empty:
            return False, {"passed": False, "reason": "no hourly data on Yahoo Finance"}

        if len(df) < self._n:
            return False, {"passed": False, "reason": f"only {len(df)} candle(s) available (need {self._n})"}

        # Take the last N *completed* candles (exclude the current live candle)
        window = df.iloc[-(self._n + 1):-1]
        if len(window) < self._n:
            window = df.iloc[-self._n:]

        green_mask = window["Close"] > window["Open"]
        green_count = int(green_mask.sum())
        ratio = green_count / len(window)

        # Latest candle (could be live – still useful for trend confirmation)
        latest = df.iloc[-1]
        last_close_above_open = bool(latest["Close"] > latest["Open"])

        # Upward drift: last close >= first open in window
        drift_up = bool(float(df.iloc[-1]["Close"]) >= float(window.iloc[0]["Open"]))

        passed = ratio >= self._min_ratio and last_close_above_open

        detail = {
            "candles_checked": len(window),
            "green_candles": green_count,
            "bullish_ratio": round(ratio, 2),
            "last_close_above_open": last_close_above_open,
            "drift_up": drift_up,
            "last_close": round(float(df.iloc[-1]["Close"]), 2),
            "passed": passed,
        }
        logger.debug(
            "%s hourly check → green=%d/%d ratio=%.2f last_green=%s passed=%s",
            symbol, green_count, len(window), ratio, last_close_above_open, passed,
        )
        return passed, detail
