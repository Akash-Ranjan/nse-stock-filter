"""
Stock Filter – main orchestrator
=================================
Pipeline:
  1. FiiDiiScanner   → symbols where FII/DII bought yesterday
  2. VolumeAnalyzer  → keep symbols whose daily volume is surging
  3. CandleAnalyzer  → keep symbols whose hourly candles are bullish
  4. Return the final filtered list with metadata for each symbol.
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.nse_client import NSEClient
from src.fii_dii_scanner import FiiDiiScanner
from src.volume_analyzer import VolumeAnalyzer
from src.candle_analyzer import CandleAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    symbol: str
    fii_dii_bought: bool = True
    volume_detail: dict = field(default_factory=dict)
    candle_detail: dict = field(default_factory=dict)
    candle_data_available: bool = True   # False when no hourly data source has coverage

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "fii_dii_bought_yesterday": self.fii_dii_bought,
            "volume": self.volume_detail,
            "hourly_candle": self.candle_detail,
            "candle_data_available": self.candle_data_available,
        }


class StockFilter:
    def __init__(self):
        self._client = NSEClient()
        self._fii_scanner = FiiDiiScanner(self._client)
        self._vol_analyzer = VolumeAnalyzer()
        self._candle_analyzer = CandleAnalyzer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, fii_date: Optional[date] = None) -> List[FilterResult]:
        """
        Execute the full filter pipeline and return passing stocks.

        Parameters
        ----------
        fii_date : date | None
            The trading date for which to check FII/DII activity.
            Defaults to the most-recent trading day.
        """
        logger.info("=" * 60)
        logger.info("Stock filter pipeline starting …")
        logger.info("=" * 60)

        # ── Step 1: FII / DII scan ──────────────────────────────────
        fii_symbols = self._fii_scanner.get_bought_symbols(for_date=fii_date)

        if not fii_symbols:
            logger.info("No FII/DII buying activity found – pipeline complete.")
            return []

        logger.info("Step 1 passed: %d symbol(s) with FII/DII buying", len(fii_symbols))

        # ── Step 2: Volume filter ────────────────────────────────────
        volume_passed: List[tuple] = []
        for symbol in sorted(fii_symbols):
            ok, detail = self._vol_analyzer.is_volume_surging(symbol)
            if ok:
                volume_passed.append((symbol, detail))

        if not volume_passed:
            logger.info("No symbols passed the volume filter.")
            return []

        logger.info("Step 2 passed: %d symbol(s) with surging volume", len(volume_passed))

        # ── Step 3: Hourly candle filter ─────────────────────────────
        final: List[FilterResult] = []
        for symbol, vol_detail in volume_passed:
            ok, candle_detail = self._candle_analyzer.is_hourly_bullish(symbol)
            reason = candle_detail.get("reason", "")
            no_data = bool(reason)

            if ok:
                final.append(FilterResult(
                    symbol=symbol,
                    volume_detail=vol_detail,
                    candle_detail=candle_detail,
                    candle_data_available=True,
                ))
            elif no_data:
                # Hourly data unavailable — include as soft pass so the user
                # can still act on the FII/DII + volume signal.
                logger.info(
                    "%s: no hourly data (%s) — included as soft pass", symbol, reason
                )
                final.append(FilterResult(
                    symbol=symbol,
                    volume_detail=vol_detail,
                    candle_detail=candle_detail,
                    candle_data_available=False,
                ))
            time.sleep(1.5)

        logger.info(
            "Step 3 passed: %d symbol(s) with bullish hourly candles", len(final)
        )
        logger.info("=" * 60)
        return final
