"""
NSE Stock Filter — Streamlit Dashboard
=======================================
Run with:
    streamlit run dashboard.py

Features
--------
• Run the full filter pipeline (FII/DII → Volume → Hourly candle) on demand
• Auto-refresh on a configurable interval
• Per-stock detail cards with volume chart and hourly candle chart
• Historical run browser (past JSON results in output/)
• Live status for each pipeline stage
"""
import os
import sys
import json
import glob
import time
from datetime import datetime

# ── SSL patch must happen before any yfinance import ──────────────────────────
try:
    from curl_cffi import requests as _curl_req
    _orig = _curl_req.Session.__init__
    def _patched(self, *a, **kw):
        kw.setdefault("verify", False)
        _orig(self, *a, **kw)
    _curl_req.Session.__init__ = _patched
except ImportError:
    pass
# ─────────────────────────────────────────────────────────────────────────────

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.dirname(__file__))
import config
from src.stock_filter import StockFilter, FilterResult
from src.candle_analyzer import _fetch_hourly_ohlcv

# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NSE Stock Filter",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Custom CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0f1117; }
    .block-container { padding-top: 1.5rem; padding-bottom: 1rem; }

    /* metric cards */
    [data-testid="metric-container"] {
        background: #1a1d2e;
        border: 1px solid #2d3250;
        border-radius: 12px;
        padding: 1rem 1.2rem;
    }
    [data-testid="metric-container"] label { color: #8b93b0 !important; font-size: 0.78rem; }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.6rem; font-weight: 700;
    }

    /* stock cards */
    .stock-card {
        background: #1a1d2e;
        border: 1px solid #2d3250;
        border-radius: 14px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 1rem;
    }
    .stock-header {
        font-size: 1.5rem; font-weight: 800; letter-spacing: 0.04em;
        color: #e8eaf6;
    }
    .badge {
        display: inline-block; padding: 2px 10px; border-radius: 20px;
        font-size: 0.72rem; font-weight: 600; margin-left: 8px;
        vertical-align: middle;
    }
    .badge-green  { background: #1b3a2d; color: #4caf77; border: 1px solid #2e6b4a; }
    .badge-blue   { background: #1a2a4a; color: #64b5f6; border: 1px solid #2a4a7a; }
    .badge-orange { background: #3a2a10; color: #ffb74d; border: 1px solid #7a5520; }

    /* stage status row */
    .stage-row { display: flex; gap: 12px; flex-wrap: wrap; margin: 0.6rem 0; }
    .stage-chip {
        padding: 4px 14px; border-radius: 20px; font-size: 0.75rem;
        font-weight: 600; border: 1px solid;
    }
    .chip-pass { background:#1b3a2d; color:#4caf77; border-color:#2e6b4a; }
    .chip-fail { background:#3a1a1a; color:#ef5350; border-color:#7a2a2a; }
    .chip-skip { background:#2a2a2a; color:#888;    border-color:#444;    }

    /* section headers */
    .section-title {
        font-size: 0.7rem; font-weight: 700; letter-spacing: 0.12em;
        text-transform: uppercase; color: #5c6bc0; margin: 0.8rem 0 0.4rem;
    }

    div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
    .stButton>button {
        border-radius: 8px; font-weight: 600;
        background: #3f4fbd; border: none; color: white;
    }
    .stButton>button:hover { background: #5060d0; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ist_now() -> str:
    return datetime.now(config.IST).strftime("%d %b %Y  %I:%M:%S %p IST")


def _load_history() -> list:
    """Load all past JSON result files, newest first."""
    files = sorted(
        glob.glob(os.path.join(config.OUTPUT_DIR, "*.json")),
        reverse=True,
    )
    results = []
    for f in files:
        try:
            with open(f) as fh:
                results.append(json.load(fh))
        except Exception:
            pass
    return results


def _save_result(results: list) -> str:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    ts = datetime.now(config.IST).strftime("%Y%m%d_%H%M")
    path = os.path.join(config.OUTPUT_DIR, f"{ts}_{config.RESULTS_FILENAME}")
    payload = {
        "run_at": datetime.now(config.IST).isoformat(),
        "total_passed": len(results),
        "stocks": [r.as_dict() for r in results],
    }
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner (with live status updates via st.status)
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(status_container) -> list:
    """Run the filter and stream status into *status_container*."""
    with status_container.status("Running pipeline…", expanded=True) as s:
        s.write("**Step 1** — Fetching FII/DII bulk & block deals from NSE…")
        fltr = StockFilter()
        fii_syms = fltr._fii_scanner.get_bought_symbols()

        if not fii_syms:
            s.write("⚠️ No FII/DII buying found.")
            s.update(label="Pipeline complete — no FII/DII activity", state="complete")
            return []

        s.write(f"✅ **{len(fii_syms)}** symbol(s) with FII/DII buying: `{'`, `'.join(sorted(fii_syms))}`")
        s.write("**Step 2** — Checking volume surge (NSE bhavcopy)…")

        vol_passed = []
        for sym in sorted(fii_syms):
            ok, detail = fltr._vol_analyzer.is_volume_surging(sym)
            icon = "✅" if ok else "❌"
            ratio = f"{detail.get('ratio', 0):.2f}×" if detail.get('ratio') else "N/A"
            s.write(f"  {icon} `{sym}` — vol ratio {ratio}")
            if ok:
                vol_passed.append((sym, detail))

        if not vol_passed:
            s.write("⚠️ No symbols passed the volume filter.")
            s.update(label="Pipeline complete — volume filter found nothing", state="complete")
            return []

        s.write(f"✅ **{len(vol_passed)}** symbol(s) passed volume check")
        s.write("**Step 3** — Checking hourly candle bullishness…")

        final = []
        for sym, vol_detail in vol_passed:
            ok, candle_detail = fltr._candle_analyzer.is_hourly_bullish(sym)
            reason = candle_detail.get("reason", "")
            if reason:
                # Hourly data unavailable from Yahoo Finance — treat as data gap, not a fail
                s.write(f"  ⚠️ `{sym}` — hourly data unavailable ({reason}); skipping")
            else:
                icon = "✅" if ok else "❌"
                ratio = f"{candle_detail.get('bullish_ratio', 0)*100:.0f}%"
                s.write(f"  {icon} `{sym}` — {ratio} bullish candles")
                if ok:
                    final.append(FilterResult(
                        symbol=sym,
                        volume_detail=vol_detail,
                        candle_detail=candle_detail,
                    ))
            time.sleep(1.5)

        label = f"Done — {len(final)} stock(s) passed all filters" if final else "Done — no stocks passed all filters"
        s.update(label=label, state="complete", expanded=False)

    return final


# ─────────────────────────────────────────────────────────────────────────────
# Chart builders
# ─────────────────────────────────────────────────────────────────────────────

def _volume_chart(symbol: str, vol_detail: dict) -> go.Figure:
    """Bar chart: yesterday's volume vs baseline average."""
    yest_vol = vol_detail.get("yesterday_vol", 0)
    avg_vol  = vol_detail.get("avg_vol", 0)
    ratio    = vol_detail.get("ratio", 0)

    # Build a small bar chart
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Avg (last 3 days)", "Yesterday"],
        y=[avg_vol, yest_vol],
        marker_color=["#3f51b5", "#4caf77" if ratio >= config.VOLUME_MULTIPLIER else "#ef5350"],
        text=[f"{avg_vol:,}", f"{yest_vol:,}"],
        textposition="outside",
        textfont=dict(color="white", size=11),
        width=0.4,
    ))
    fig.add_hline(
        y=avg_vol * config.VOLUME_MULTIPLIER,
        line_dash="dot", line_color="#ffb74d",
        annotation_text=f"Threshold ({config.VOLUME_MULTIPLIER}×)",
        annotation_font_color="#ffb74d",
    )
    fig.update_layout(
        title=dict(text=f"{symbol} — Daily Volume", font=dict(color="#e8eaf6", size=14)),
        paper_bgcolor="#1a1d2e", plot_bgcolor="#1a1d2e",
        font=dict(color="#8b93b0"),
        xaxis=dict(gridcolor="#2d3250", linecolor="#2d3250"),
        yaxis=dict(gridcolor="#2d3250", linecolor="#2d3250", tickformat=","),
        margin=dict(t=50, b=40, l=60, r=20),
        height=280,
        showlegend=False,
    )
    return fig


def _hourly_candle_chart(symbol: str):
    """Candlestick chart of the last 5 days of 1h candles."""
    df = _fetch_hourly_ohlcv(symbol)
    if df is None or df.empty:
        return None

    # Keep last 30 candles for readability
    df = df.tail(30).copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    fig = go.Figure(data=[go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],  close=df["Close"],
        increasing_line_color="#4caf77",
        decreasing_line_color="#ef5350",
        increasing_fillcolor="#4caf77",
        decreasing_fillcolor="#ef5350",
    )])

    # Highlight the last N candles window
    n = config.HOURLY_CANDLES_TO_CHECK
    if len(df) >= n:
        window_start = df.index[-(n + 1)]
        fig.add_vrect(
            x0=window_start, x1=df.index[-1],
            fillcolor="#3f51b5", opacity=0.12,
            layer="below", line_width=0,
            annotation_text="Checked window",
            annotation_font_color="#5c6bc0",
        )

    fig.update_layout(
        title=dict(text=f"{symbol} — Hourly Candles (last 30)", font=dict(color="#e8eaf6", size=14)),
        paper_bgcolor="#1a1d2e", plot_bgcolor="#1a1d2e",
        font=dict(color="#8b93b0"),
        xaxis=dict(
            gridcolor="#2d3250", linecolor="#2d3250",
            rangeslider=dict(visible=False),
            type="category",
            tickangle=-45, tickfont=dict(size=9),
        ),
        yaxis=dict(gridcolor="#2d3250", linecolor="#2d3250"),
        margin=dict(t=50, b=60, l=60, r=20),
        height=320,
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Stock detail card
# ─────────────────────────────────────────────────────────────────────────────

def _render_stock_card(r: FilterResult) -> None:
    vol = r.volume_detail
    cnd = r.candle_detail

    vol_ratio    = vol.get("ratio", 0)
    bull_pct     = int(cnd.get("bullish_ratio", 0) * 100)
    last_price   = cnd.get("last_close", "—")
    green_cnt    = cnd.get("green_candles", 0)
    total_cnt    = cnd.get("candles_checked", 0)
    drift        = cnd.get("drift_up", False)

    st.markdown(f"""
    <div class="stock-card">
      <span class="stock-header">📊 {r.symbol}</span>
      <span class="badge badge-green">FII/DII Bought</span>
      <span class="badge badge-orange">Vol {vol_ratio:.2f}×</span>
      <span class="badge badge-blue">{bull_pct}% Bullish</span>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last Close",      f"₹{last_price}" if isinstance(last_price, float) else "—")
    c2.metric("Volume Ratio",    f"{vol_ratio:.2f}×", delta="surging" if vol_ratio >= config.VOLUME_MULTIPLIER else None)
    c3.metric("Green Candles",   f"{green_cnt} / {total_cnt}")
    c4.metric("Price Drift Up",  "Yes" if drift else "No")

    col_v, col_c = st.columns(2)
    with col_v:
        fig_v = _volume_chart(r.symbol, vol)
        st.plotly_chart(fig_v, use_container_width=True, key=f"vol_{r.symbol}")
    with col_c:
        fig_c = _hourly_candle_chart(r.symbol)
        if fig_c:
            st.plotly_chart(fig_c, use_container_width=True, key=f"candle_{r.symbol}")
        else:
            st.info("Hourly candle data unavailable.")


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Settings")
    st.markdown("---")

    st.markdown("**Volume Filter**")
    vol_mult = st.slider("Min volume multiplier", 1.0, 5.0,
                         float(config.VOLUME_MULTIPLIER), 0.1,
                         help="Yesterday vol must be ≥ N× the 3-day avg")
    vol_days = st.slider("Lookback days", 2, 7, config.VOLUME_LOOKBACK_DAYS,
                         help="Days used for baseline volume average")

    st.markdown("**Hourly Candle Filter**")
    candle_n = st.slider("Candles to check", 2, 6,
                         config.HOURLY_CANDLES_TO_CHECK)
    bull_ratio = st.slider("Min bullish %", 50, 100,
                           int(config.BULLISH_CANDLE_MIN_RATIO * 100), 5)

    # Apply to config live
    config.VOLUME_MULTIPLIER        = vol_mult
    config.VOLUME_LOOKBACK_DAYS     = vol_days
    config.HOURLY_CANDLES_TO_CHECK  = candle_n
    config.BULLISH_CANDLE_MIN_RATIO = bull_ratio / 100.0

    st.markdown("---")
    st.markdown("**Schedule**")
    st.info("Fires automatically every weekday at **10:15 AM IST**\nvia `python main.py`")
    st.markdown("---")

    st.caption(f"🕐 {_ist_now()}")


# ─────────────────────────────────────────────────────────────────────────────
# Main layout
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("# 📈 NSE Stock Filter Dashboard")
st.markdown(
    "Scans NSE for stocks where **FII/DII bought yesterday**, "
    "**volume is surging**, and **hourly candles are bullish**."
)
st.markdown("---")

# ── Top KPI strip ─────────────────────────────────────────────────────────────
history = _load_history()
last_run = history[0] if history else None

k1, k2, k3, k4 = st.columns(4)
k1.metric("Last Run",
          datetime.fromisoformat(last_run["run_at"]).strftime("%d %b %H:%M") if last_run else "Never")
k2.metric("Stocks Found (last run)",
          str(last_run["total_passed"]) if last_run else "—")
k3.metric("Total Historical Runs", str(len(history)))
k4.metric("Volume Threshold",      f"{config.VOLUME_MULTIPLIER:.1f}×")

st.markdown("---")

# ── Run panel ─────────────────────────────────────────────────────────────────
tab_live, tab_history = st.tabs(["🚀 Run Filter Now", "📂 Past Results"])

# ── TAB 1: Live run ───────────────────────────────────────────────────────────
with tab_live:
    col_btn, col_note = st.columns([2, 5])
    with col_btn:
        run_clicked = st.button("▶  Run Filter", type="primary", use_container_width=True)
    with col_note:
        st.markdown(
            "<br><small style='color:#8b93b0'>Downloads fresh NSE data and runs all 3 pipeline stages</small>",
            unsafe_allow_html=True,
        )

    if run_clicked:
        status_box = st.empty()
        with st.spinner(""):
            results = run_pipeline(status_box)

        if results:
            _save_result(results)
            st.success(f"✅ **{len(results)} stock(s)** passed all three filters!")
            for r in results:
                _render_stock_card(r)
        else:
            st.warning("No stocks satisfied all three conditions in this run.")

        # Summary table
        if results:
            st.markdown("### Summary Table")
            rows = []
            for r in results:
                rows.append({
                    "Symbol":       r.symbol,
                    "Last Close":   f"₹{r.candle_detail.get('last_close', '—')}",
                    "Yest. Volume": f"{r.volume_detail.get('yesterday_vol', 0):,}",
                    "Vol Ratio":    f"{r.volume_detail.get('ratio', 0):.2f}×",
                    "Green Candles":f"{r.candle_detail.get('green_candles',0)}/{r.candle_detail.get('candles_checked',0)}",
                    "Drift Up":     "✅" if r.candle_detail.get("drift_up") else "❌",
                })
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
            )

    else:
        st.info("Click **▶ Run Filter** to scan NSE now, or use `python main.py` for the automated 10:15 AM schedule.")


# ── TAB 2: History ────────────────────────────────────────────────────────────
with tab_history:
    if not history:
        st.info("No past results yet. Run the filter at least once.")
    else:
        # Run selector
        run_labels = [
            f"{r['run_at'][:16].replace('T',' ')}  —  {r['total_passed']} stock(s)"
            for r in history
        ]
        selected_idx = st.selectbox("Select a past run", range(len(run_labels)),
                                    format_func=lambda i: run_labels[i])
        chosen = history[selected_idx]

        run_dt = datetime.fromisoformat(chosen["run_at"]).strftime("%d %b %Y %I:%M %p IST")
        st.markdown(f"**Run at:** {run_dt}  |  **Stocks found:** {chosen['total_passed']}")

        if chosen["stocks"]:
            # Summary table for the selected run
            rows = []
            for s in chosen["stocks"]:
                vol = s.get("volume", {})
                cnd = s.get("hourly_candle", {})
                rows.append({
                    "Symbol":        s["symbol"],
                    "Vol Ratio":     f"{vol.get('ratio', 0):.2f}×",
                    "Yest. Volume":  f"{vol.get('yesterday_vol', 0):,}",
                    "Avg Volume":    f"{vol.get('avg_vol', 0):,}",
                    "Green Candles": f"{cnd.get('green_candles',0)}/{cnd.get('candles_checked',0)}",
                    "Last Close":    f"₹{cnd.get('last_close','—')}",
                    "Drift Up":      "✅" if cnd.get("drift_up") else "❌",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Chart for each stock
            for s in chosen["stocks"]:
                with st.expander(f"📊 {s['symbol']} — Charts"):
                    c1, c2 = st.columns(2)
                    with c1:
                        fig_v = _volume_chart(s["symbol"], s.get("volume", {}))
                        st.plotly_chart(fig_v, use_container_width=True,
                                        key=f"hist_vol_{s['symbol']}_{selected_idx}")
                    with c2:
                        fig_c = _hourly_candle_chart(s["symbol"])
                        if fig_c:
                            st.plotly_chart(fig_c, use_container_width=True,
                                            key=f"hist_candle_{s['symbol']}_{selected_idx}")
                        else:
                            st.info("Hourly candle data unavailable.")
        else:
            st.warning("No stocks passed the filter in this run.")

        # Raw JSON viewer
        with st.expander("🔍 Raw JSON"):
            st.json(chosen)
