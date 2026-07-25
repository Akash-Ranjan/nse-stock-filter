#!/usr/bin/env python3
"""
NSE Stock Filter – main entry point
=====================================
Runs the full filter pipeline at 10:15 AM IST every weekday and prints /
saves matching stocks.

Usage
-----
  # Run immediately (one-shot, useful for testing)
  python main.py --now

  # Start the scheduler (blocks; fires every weekday at 10:15 AM IST)
  python main.py

  # Run for a specific date's FII/DII data
  python main.py --now --date 2024-05-10
"""
import os

# Disable SSL certificate verification globally for curl_cffi and requests.
# Required on networks with corporate SSL inspection (Zscaler, Cisco Umbrella,
# etc.) that intercept HTTPS and re-sign with a self-signed CA.
os.environ.setdefault("CURL_CA_BUNDLE", "")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "")
os.environ.setdefault("SSL_CERT_FILE", "")

# curl_cffi (used by yfinance ≥1.2) reads verify= at Session construction
# time, not from env vars.  Patch the default before yfinance is imported.
try:
    from curl_cffi import requests as _curl_req
    _orig_curl_init = _curl_req.Session.__init__
    def _patched_curl_init(self, *args, **kwargs):
        kwargs.setdefault("verify", False)
        _orig_curl_init(self, *args, **kwargs)
    _curl_req.Session.__init__ = _patched_curl_init
except ImportError:
    pass

import argparse
import logging
import sys
from datetime import date, datetime
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from src.stock_filter import StockFilter
from src.reporter import print_results, save_results

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core job
# ---------------------------------------------------------------------------

def run_filter(fii_date: Optional[date] = None) -> None:
    """Execute the pipeline, print results, and persist them to disk."""
    logger.info(
        "Running NSE stock filter at %s",
        datetime.now(config.IST).strftime("%Y-%m-%d %H:%M:%S %Z"),
    )
    fltr = StockFilter()
    results = fltr.run(fii_date=fii_date)
    print_results(results)
    if results:
        path = save_results(results)
        print(f"\n  Results also saved → {path}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NSE stock filter: FII/DII + volume surge + hourly bullishness"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run the filter immediately instead of waiting for 10:15 AM IST",
    )
    parser.add_argument(
        "--date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        metavar="YYYY-MM-DD",
        help="Override the FII/DII check date (default: previous trading day)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.now:
        run_filter(fii_date=args.date)
        return

    # ------------------------------------------------------------------
    # Scheduled mode: fire every weekday at 10:15 AM IST
    # ------------------------------------------------------------------
    scheduler = BlockingScheduler(timezone=config.IST)
    scheduler.add_job(
        run_filter,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=config.SCHEDULE_HOUR,
            minute=config.SCHEDULE_MINUTE,
            timezone=config.IST,
        ),
        id="nse_stock_filter",
        name="NSE Stock Filter",
        misfire_grace_time=300,   # allow up to 5-min late start
        coalesce=True,
    )

    next_run = scheduler.get_jobs()[0].next_run_time
    if next_run:
        logger.info(
            "Scheduler started. Next run: %s",
            next_run.strftime("%a %d %b %Y  %I:%M %p %Z"),
        )
    else:
        logger.info("Scheduler started. Next run time will be set on first tick.")
    logger.info("Press Ctrl-C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
