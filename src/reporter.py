"""
Reporter
========
Formats and persists the final list of filtered stocks.
"""
import json
import logging
import os
from datetime import datetime
from typing import List

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from src.stock_filter import FilterResult

logger = logging.getLogger(__name__)

try:
    from tabulate import tabulate
    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False


def _summary_row(r: FilterResult) -> list:
    vol = r.volume_detail
    cnd = r.candle_detail
    return [
        r.symbol,
        f"{vol.get('yesterday_vol', 'N/A'):,}" if isinstance(vol.get('yesterday_vol'), int) else "N/A",
        f"{vol.get('ratio', 'N/A'):.2f}x" if isinstance(vol.get('ratio'), float) else "N/A",
        f"{cnd.get('bullish_ratio', 0) * 100:.0f}%" if isinstance(cnd.get('bullish_ratio'), float) else "N/A",
        f"₹{cnd.get('last_close', 'N/A')}" if isinstance(cnd.get('last_close'), float) else "N/A",
    ]


def print_results(results: List[FilterResult]) -> None:
    ts = datetime.now(config.IST).strftime("%d %b %Y  %I:%M %p IST")

    print("\n")
    print("┌" + "─" * 62 + "┐")
    print(f"│  NSE Stock Filter Results  –  {ts:^30} │")
    print("└" + "─" * 62 + "┘")

    if not results:
        print("\n  ⚠  No stocks satisfied all three conditions today.\n")
        return

    print(f"\n  {len(results)} stock(s) passed all filters:\n")

    headers = ["Symbol", "Yest. Volume", "Vol Ratio", "Bullish %", "Last Price"]
    rows = [_summary_row(r) for r in results]

    if _HAS_TABULATE:
        print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
    else:
        col_w = [max(len(h), max((len(str(row[i])) for row in rows), default=0))
                 for i, h in enumerate(headers)]
        fmt = "  ".join(f"{{:<{w}}}" for w in col_w)
        print("  " + fmt.format(*headers))
        print("  " + "  ".join("-" * w for w in col_w))
        for row in rows:
            print("  " + fmt.format(*[str(c) for c in row]))

    print()


def save_results(results: List[FilterResult]) -> str:
    """Save results as JSON and return the file path."""
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    ts = datetime.now(config.IST).strftime("%Y%m%d_%H%M")
    filename = f"{ts}_{config.RESULTS_FILENAME}"
    path = os.path.join(config.OUTPUT_DIR, filename)

    payload = {
        "run_at": datetime.now(config.IST).isoformat(),
        "total_passed": len(results),
        "stocks": [r.as_dict() for r in results],
    }

    with open(path, "w") as f:
        json.dump(payload, f, indent=2)

    logger.info("Results saved to %s", path)
    return path
