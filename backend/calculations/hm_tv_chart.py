"""TradingView Lightweight Charts renderer for the H-M Scanner page.

Vendored LWC JS lives at app/static/lightweight-charts.standalone.production.js
so the dashboard has no CDN dependency (Streamlit Cloud has a strict CSP).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.calculations.hm_indicators import ema

_STATIC_DIR = Path(__file__).parent.parent.parent / "app" / "static"
_LWC_JS = (_STATIC_DIR / "lightweight-charts.standalone.production.js").read_text(encoding="utf-8")

INTERVAL_YF_TO_TV = {
    "15m": "15", "30m": "30", "1h": "60",
    "1d": "1D", "1wk": "1W", "1mo": "1M",
}


def to_tv_symbol(yf_symbol: str) -> str:
    """'RELIANCE.NS' -> 'NSE:RELIANCE'"""
    s = yf_symbol.strip().upper()
    if ":" in s:
        return s
    if "." not in s:
        return s
    ticker, suffix = s.rsplit(".", 1)
    exchange = {"NS": "NSE", "BO": "BSE"}.get(suffix)
    return f"{exchange}:{ticker}" if exchange else ticker


def tv_chart_url(yf_symbol: str, interval: str = "1d") -> str:
    """Returns TradingView chart URL for a yfinance symbol."""
    tv_sym = to_tv_symbol(yf_symbol)
    tv_tf = INTERVAL_YF_TO_TV.get(interval, "1D")
    return f"https://www.tradingview.com/chart/?symbol={tv_sym}&interval={tv_tf}"


def _to_unix_seconds(index: pd.DatetimeIndex) -> list[int]:
    idx = index
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC")
    return idx.values.astype("datetime64[s]").astype("int64").tolist()


def _line_series(times: list[int], values: pd.Series) -> list[dict]:
    return [
        {"time": t, "value": float(v)} if pd.notna(v) else {"time": t}
        for t, v in zip(times, values)
    ]


def build_tv_chart_html(
    df: pd.DataFrame,
    symbol: str,
    main_height: int = 460,
    osc_height: int = 200,
    max_bars: int = 1000,
    show_ema: bool = True,
    ema_period: int = 20,
    show_signal_lines: bool = True,
    bottom_line_color: str = "#26a69a",
    top_line_color: str = "#ff9100",
) -> str:
    plot_df = df.tail(max_bars).copy()
    times = _to_unix_seconds(plot_df.index)

    candles = [
        {"time": t, "open": float(o), "high": float(h), "low": float(l), "close": float(c)}
        for t, o, h, l, c in zip(times, plot_df["Open"], plot_df["High"], plot_df["Low"], plot_df["Close"])
        if pd.notna(o) and pd.notna(h) and pd.notna(l) and pd.notna(c)
    ]

    bottom_mask = plot_df["BOTTOM_SIGNAL"].fillna(False)
    top_mask = plot_df["TOP_SIGNAL"].fillna(False)

    main_markers = sorted(
        [{"time": t, "position": "belowBar", "color": "#26a69a", "shape": "circle", "text": "B", "size": 2}
         for t, hit in zip(times, bottom_mask) if hit]
        + [{"time": t, "position": "aboveBar", "color": "#ef5350", "shape": "circle", "text": "T", "size": 2}
           for t, hit in zip(times, top_mask) if hit],
        key=lambda m: m["time"],
    )

    osc_markers = sorted(
        [{"time": t, "position": "inBar", "color": "#26a69a", "shape": "circle", "size": 1.5}
         for t, hit in zip(times, bottom_mask) if hit]
        + [{"time": t, "position": "inBar", "color": "#ef5350", "shape": "circle", "size": 1.5}
           for t, hit in zip(times, top_mask) if hit],
        key=lambda m: m["time"],
    )

    ema_data = _line_series(times, ema(plot_df["Close"], ema_period)) if show_ema else []
    bottom_times = [t for t, hit in zip(times, bottom_mask) if hit]
    top_times = [t for t, hit in zip(times, top_mask) if hit]

    payload = {
        "candles": candles,
        "mainMarkers": main_markers,
        "rsi": _line_series(times, plot_df["RSI"]),
        "wma": _line_series(times, plot_df["HM_WMA"]),
        "hmEma": _line_series(times, plot_df["HM_EMA"]),
        "oscMarkers": osc_markers,
        "symbol": symbol,
        "priceEma": ema_data,
        "emaPeriod": ema_period,
        "signalLines": {
            "show": bool(show_signal_lines),
            "bottomTimes": bottom_times,
            "topTimes": top_times,
            "bottomColor": bottom_line_color,
            "topColor": top_line_color,
        },
    }

    return (
        _HTML_TEMPLATE
        .replace("__LWC_JS__", _LWC_JS)
        .replace("__DATA_JSON__", json.dumps(payload))
        .replace("__MAIN_HEIGHT__", str(main_height))
        .replace("__OSC_HEIGHT__", str(osc_height))
        .replace("__SYMBOL__", symbol)
    )


def render_tv_chart(
    df: pd.DataFrame,
    symbol: str,
    main_height: int = 460,
    osc_height: int = 200,
    max_bars: int = 1000,
    show_ema: bool = True,
    ema_period: int = 20,
    show_signal_lines: bool = True,
    bottom_line_color: str = "#26a69a",
    top_line_color: str = "#ff9100",
) -> None:
    import streamlit as st
    html = build_tv_chart_html(
        df, symbol, main_height=main_height, osc_height=osc_height,
        max_bars=max_bars, show_ema=show_ema, ema_period=ema_period,
        show_signal_lines=show_signal_lines,
        bottom_line_color=bottom_line_color, top_line_color=top_line_color,
    )
    st.components.v1.html(html, height=main_height + osc_height + 40, scrolling=False)


_HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; padding: 0; background: #131722; overflow: hidden; }
  #tv-symbol { color: #d1d4dc; font: 600 13px sans-serif; padding: 4px 8px; }
  #tv-main-chart { height: __MAIN_HEIGHT__px; }
  #tv-osc-chart { height: __OSC_HEIGHT__px; }
</style>
</head>
<body>
  <div id="tv-symbol">__SYMBOL__ &middot; H-M System (RSI 9 / WMA 21)</div>
  <div id="tv-main-chart"></div>
  <div id="tv-osc-chart"></div>
  <script>__LWC_JS__</script>
  <script>
    const DATA = __DATA_JSON__;

    const mainEl = document.getElementById('tv-main-chart');
    const oscEl = document.getElementById('tv-osc-chart');

    const commonOptions = {
      layout: { background: { type: 'solid', color: '#131722' }, textColor: '#d1d4dc' },
      grid: {
        vertLines: { color: 'rgba(42, 46, 57, 0.6)' },
        horzLines: { color: 'rgba(42, 46, 57, 0.6)' },
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#2a2e39', minimumWidth: 70 },
    };

    const mainChart = LightweightCharts.createChart(mainEl, Object.assign({}, commonOptions, {
      width: mainEl.clientWidth,
      height: __MAIN_HEIGHT__,
      timeScale: { visible: false, borderColor: '#2a2e39' },
    }));

    const candleSeries = mainChart.addSeries(LightweightCharts.CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candleSeries.setData(DATA.candles);
    LightweightCharts.createSeriesMarkers(candleSeries, DATA.mainMarkers);

    if (DATA.priceEma && DATA.priceEma.length) {
      const emaSeries = mainChart.addSeries(LightweightCharts.LineSeries, {
        color: '#2962ff', lineWidth: 2, priceLineVisible: false, title: 'EMA ' + DATA.emaPeriod,
      });
      emaSeries.setData(DATA.priceEma);
    }

    const oscChart = LightweightCharts.createChart(oscEl, Object.assign({}, commonOptions, {
      width: oscEl.clientWidth,
      height: __OSC_HEIGHT__,
      timeScale: { visible: true, borderColor: '#2a2e39', timeVisible: true, secondsVisible: false },
    }));

    const rsiFillSeries = oscChart.addSeries(LightweightCharts.BaselineSeries, {
      baseValue: { type: 'price', price: 50 },
      lineVisible: false,
      topLineColor: 'rgba(0,0,0,0)', topFillColor1: 'rgba(255,0,0,0.25)', topFillColor2: 'rgba(255,0,0,0.25)',
      bottomLineColor: 'rgba(0,0,0,0)', bottomFillColor1: 'rgba(0,128,0,0.25)', bottomFillColor2: 'rgba(0,128,0,0.25)',
      lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
    });
    rsiFillSeries.setData(DATA.rsi);

    const rsiSeries = oscChart.addSeries(LightweightCharts.LineSeries, { color: '#ffffff', lineWidth: 1, priceLineVisible: false });
    rsiSeries.setData(DATA.rsi);
    rsiSeries.createPriceLine({
      price: 50, color: '#00ffff', lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: '50',
    });
    LightweightCharts.createSeriesMarkers(rsiSeries, DATA.oscMarkers);

    const emaSeries = oscChart.addSeries(LightweightCharts.LineSeries, { color: '#00ff00', lineWidth: 2, priceLineVisible: false });
    emaSeries.setData(DATA.hmEma);

    const wmaSeries = oscChart.addSeries(LightweightCharts.LineSeries, { color: '#ff0000', lineWidth: 2, priceLineVisible: false });
    wmaSeries.setData(DATA.wma);

    mainEl.style.position = 'relative';
    oscEl.style.position = 'relative';

    function makeVLine(color) {
      const el = document.createElement('div');
      el.style.position = 'absolute';
      el.style.top = '0';
      el.style.bottom = '0';
      el.style.width = '0';
      el.style.borderLeft = '1px dashed ' + color;
      el.style.pointerEvents = 'none';
      el.style.zIndex = '5';
      return el;
    }

    function positionVLine(el, chart, time) {
      const x = chart.timeScale().timeToCoordinate(time);
      if (x === null) { el.style.display = 'none'; return; }
      el.style.display = 'block';
      el.style.left = x + 'px';
    }

    const vLines = [];
    if (DATA.signalLines && DATA.signalLines.show) {
      DATA.signalLines.bottomTimes.forEach((t) => {
        vLines.push({ time: t, mainEl: makeVLine(DATA.signalLines.bottomColor), oscEl: makeVLine(DATA.signalLines.bottomColor) });
      });
      DATA.signalLines.topTimes.forEach((t) => {
        vLines.push({ time: t, mainEl: makeVLine(DATA.signalLines.topColor), oscEl: makeVLine(DATA.signalLines.topColor) });
      });
      vLines.forEach((v) => { mainEl.appendChild(v.mainEl); oscEl.appendChild(v.oscEl); });
    }

    function refreshVLines() {
      vLines.forEach((v) => {
        positionVLine(v.mainEl, mainChart, v.time);
        positionVLine(v.oscEl, oscChart, v.time);
      });
    }

    function syncRange(a, b) {
      a.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) b.timeScale().setVisibleLogicalRange(range);
        refreshVLines();
      });
    }
    syncRange(mainChart, oscChart);
    syncRange(oscChart, mainChart);

    function crosshairValue(dataPoint) {
      if (dataPoint === null || dataPoint === undefined) return undefined;
      return 'close' in dataPoint ? dataPoint.close : dataPoint.value;
    }

    mainChart.subscribeCrosshairMove((param) => {
      if (!param.time) { oscChart.clearCrosshairPosition(); return; }
      const pt = param.seriesData.get(candleSeries);
      if (pt) oscChart.setCrosshairPosition(crosshairValue(pt), param.time, rsiSeries);
      else oscChart.clearCrosshairPosition();
    });
    oscChart.subscribeCrosshairMove((param) => {
      if (!param.time) { mainChart.clearCrosshairPosition(); return; }
      const pt = param.seriesData.get(rsiSeries);
      if (pt) mainChart.setCrosshairPosition(crosshairValue(pt), param.time, candleSeries);
      else mainChart.clearCrosshairPosition();
    });

    mainChart.timeScale().fitContent();
    oscChart.timeScale().fitContent();
    refreshVLines();

    window.addEventListener('resize', () => {
      mainChart.resize(mainEl.clientWidth, __MAIN_HEIGHT__);
      oscChart.resize(oscEl.clientWidth, __OSC_HEIGHT__);
      refreshVLines();
    });
  </script>
</body>
</html>"""
