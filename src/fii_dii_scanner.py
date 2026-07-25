"""
FII / DII Scanner
=================
Downloads bulk-deal and block-deal CSV files from the NSE public archive
and returns the set of symbols where an FII or DII was a net buyer.

Archive CSV columns
-------------------
  Date, Symbol, Security Name, Client Name, Buy/Sell,
  Quantity Traded, Trade Price / Wght. Avg. Price, Remarks

FII/DII identification
----------------------
We match Client Name against config.FII_DII_KEYWORDS (case-insensitive).
Add fund names to that list in config.py to improve coverage.
"""
import io
import logging
from datetime import date, timedelta
from typing import Optional, Set

import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from src.nse_client import NSEClient

logger = logging.getLogger(__name__)

_BULK_CSV_PATH  = "/content/equities/bulk.csv"
_BLOCK_CSV_PATH = "/content/equities/block.csv"


def _prev_trading_day() -> date:
    """Return the most recent weekday before today (skips weekends only)."""
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _is_fii_dii(client_name: str) -> bool:
    name_lower = str(client_name).lower()
    return any(kw in name_lower for kw in config.FII_DII_KEYWORDS)


def _parse_csv(csv_text: str, target_date: date) -> pd.DataFrame:
    """
    Parse a bulk/block CSV string and return only rows matching *target_date*.
    Returns an empty DataFrame if parsing fails.
    """
    try:
        df = pd.read_csv(io.StringIO(csv_text))
    except Exception as exc:
        logger.warning("CSV parse error: %s", exc)
        return pd.DataFrame()

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_").replace("/", "_") for c in df.columns]

    # Filter to the target date (NSE formats: '24-JUL-2026')
    if "date" in df.columns:
        target_str = target_date.strftime("%d-%b-%Y").upper()  # e.g. 24-JUL-2026
        df = df[df["date"].str.upper().str.strip() == target_str]

    return df


def _net_buyer_symbols(df: pd.DataFrame) -> Set[str]:
    """
    From a parsed deals DataFrame return symbols where total FII/DII buy qty
    exceeds total FII/DII sell qty.
    """
    if df.empty:
        return set()

    # Identify the buy/sell and quantity columns
    buy_sell_col = next((c for c in df.columns if "buy" in c and "sell" in c), None)
    qty_col = next((c for c in df.columns if "quantity" in c or "qty" in c), None)
    client_col = next((c for c in df.columns if "client" in c), None)
    symbol_col = "symbol" if "symbol" in df.columns else None

    if not all([buy_sell_col, qty_col, client_col, symbol_col]):
        logger.warning("Could not identify required columns. Found: %s", list(df.columns))
        return set()

    df = df.copy()
    df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0)
    df["is_inst"] = df[client_col].apply(_is_fii_dii)

    inst = df[df["is_inst"]].copy()
    if inst.empty:
        return set()

    inst["signed_qty"] = inst.apply(
        lambda r: r[qty_col] if str(r[buy_sell_col]).strip().upper() == "BUY" else -r[qty_col],
        axis=1,
    )
    net = inst.groupby(symbol_col)["signed_qty"].sum()
    return set(net[net > 0].index.str.upper())


class FiiDiiScanner:
    def __init__(self, client: NSEClient):
        self._client = client

    def get_bought_symbols(self, for_date: Optional[date] = None) -> Set[str]:
        """
        Return symbols where FII or DII was a net buyer on *for_date*
        (defaults to the previous trading day).
        """
        target = for_date or _prev_trading_day()
        logger.info("Scanning FII/DII activity for %s …", target.strftime("%d-%b-%Y"))

        bulk_text  = self._client.fetch_csv_text(_BULK_CSV_PATH)
        block_text = self._client.fetch_csv_text(_BLOCK_CSV_PATH)

        bulk_df  = _parse_csv(bulk_text,  target) if bulk_text  else pd.DataFrame()
        block_df = _parse_csv(block_text, target) if block_text else pd.DataFrame()

        bulk_syms  = _net_buyer_symbols(bulk_df)
        block_syms = _net_buyer_symbols(block_df)

        logger.info(
            "Bulk deals: %d FII/DII buyer symbols  |  Block deals: %d",
            len(bulk_syms), len(block_syms),
        )

        bought = bulk_syms | block_syms
        logger.info("Total FII/DII bought symbols: %d", len(bought))

        if bought:
            logger.info("Symbols: %s", ", ".join(sorted(bought)))

        return bought
