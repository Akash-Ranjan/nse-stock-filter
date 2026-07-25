"""
NSE Archive client
==================
Downloads bulk-deal and block-deal CSV files from NSE's public archive server
(nsearchives.nseindia.com).  These endpoints require no authentication, no
cookies, and are not protected by Cloudflare — they are the most stable way
to get daily deal data programmatically.

Archive URLs
------------
  https://nsearchives.nseindia.com/content/equities/bulk.csv   – latest bulk deals
  https://nsearchives.nseindia.com/content/equities/block.csv  – latest block deals

Both files are updated after market close and always contain the most-recent
trading day's data.
"""
import logging
import time
from typing import Optional

import requests
import urllib3

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_ARCHIVE_BASE = "https://nsearchives.nseindia.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class NSEClient:
    """Lightweight client for NSE archive CSV downloads."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        self._session.verify = False

    def fetch_csv_text(self, path: str) -> Optional[str]:
        """
        Download a CSV from *path* (relative to the archive base URL).
        Returns the raw text on success, None on failure.
        """
        url = f"{_ARCHIVE_BASE}{path}"
        for attempt in range(1, config.NSE_RETRY_ATTEMPTS + 1):
            try:
                resp = self._session.get(url, timeout=config.NSE_REQUEST_TIMEOUT)
                resp.raise_for_status()
                logger.debug("Downloaded %s (%d bytes)", url, len(resp.content))
                return resp.text
            except requests.RequestException as exc:
                logger.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt, config.NSE_RETRY_ATTEMPTS, url, exc,
                )
                if attempt < config.NSE_RETRY_ATTEMPTS:
                    time.sleep(config.NSE_RETRY_DELAY * attempt)
        logger.error("All %d attempts failed for %s", config.NSE_RETRY_ATTEMPTS, url)
        return None
