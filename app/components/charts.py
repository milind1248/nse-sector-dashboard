"""Reusable Plotly chart builders."""
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from typing import Optional


def candlestick_with_emas(df: pd.DataFrame, title: str = "") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=list(df.index),
        open=df["Open"],  high=df["High"],
        low=df["Low"],   close=df["Close"],
        name="OHLC", increasing_line_color="#00C853", decreasing_line_color="#D50000",
    ))
    colors = {"EMA20": "#FFD600", "EMA50": "#FF6D00", "EMA200": "#2979FF"}
    try:
        close = df["Close"]
        for period, label in [(20, "EMA20"), (50, "EMA50"), (200, "EMA200")]:
            ema = close.ewm(span=period, adjust=False).mean()
            if not ema.dropna().empty:
                fig.add_trace(go.Scatter(
                    x=list(df.index), y=ema,
                    mode="lines", name=label,
                    line=dict(color=colors[label], width=1.5),
                ))
    except Exception:
        pass

    fig.update_layout(
        title=title, template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=420, margin=dict(t=40, b=20, l=10, r=10),
    )
    return fig


def rsi_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    try:
        close = df["Close"]
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = 100 - (100 / (1 + rs))
        fig.add_trace(go.Scatter(x=list(df.index), y=rsi, name="RSI(14)",
                                  line=dict(color="#AB47BC", width=2)))
        fig.add_hline(y=70, line_dash="dot", line_color="#D50000", opacity=0.6)
        fig.add_hline(y=30, line_dash="dot", line_color="#00C853", opacity=0.6)
        fig.add_hrect(y0=70, y1=100, fillcolor="#D50000", opacity=0.05, line_width=0)
        fig.add_hrect(y0=0,  y1=30,  fillcolor="#00C853", opacity=0.05, line_width=0)
    except Exception:
        pass
    fig.update_layout(template="plotly_dark", height=180,
                       margin=dict(t=10, b=20, l=10, r=10),
                       yaxis=dict(range=[0, 100]))
    return fig


def sector_heatmap(df: pd.DataFrame) -> go.Figure:
    """df: rows=sectors, cols=return periods (1W, 2W, etc.)"""
    fig = px.imshow(
        df,
        color_continuous_scale="RdYlGn",
        zmin=-10, zmax=10,
        text_auto=".1f",
        aspect="auto",
    )
    fig.update_layout(
        template="plotly_dark", height=max(400, len(df) * 25),
        margin=dict(t=20, b=20, l=120, r=20),
        coloraxis_colorbar=dict(title="%"),
    )
    return fig


def fii_bar_chart(df: pd.DataFrame, col: str = "fii_net", title: str = "FII Net Flow") -> go.Figure:
    colors = ["#00C853" if v >= 0 else "#D50000" for v in df[col]]
    fig = go.Figure(go.Bar(x=df["date"].astype(str), y=df[col], marker_color=colors, name=col))
    fig.update_layout(template="plotly_dark", title=title, height=300,
                       margin=dict(t=40, b=20, l=10, r=10))
    return fig


def rrg_chart(rrg_data: list[dict]) -> go.Figure:
    fig = go.Figure()
    colors = {"Leading": "#00C853", "Improving": "#00BCD4",
               "Lagging": "#D50000",  "Weakening": "#FF6D00"}

    for item in rrg_data:
        trail = item.get("trail", [])
        if len(trail) > 1:
            xs = [t["rs_ratio"] for t in trail[:-1]]
            ys = [t["rs_momentum"] for t in trail[:-1]]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                      line=dict(color=colors.get(item["quadrant"], "#888"), width=1),
                                      showlegend=False, opacity=0.4))
        fig.add_trace(go.Scatter(
            x=[item["rs_ratio"]], y=[item["rs_momentum"]],
            mode="markers+text",
            marker=dict(size=14, color=colors.get(item["quadrant"], "#888"),
                        line=dict(width=1, color="white")),
            text=[item["sector"]], textposition="top center",
            textfont=dict(size=10),
            name=item["quadrant"],
            showlegend=False,
        ))

    fig.add_vline(x=100, line_dash="dot", line_color="white", opacity=0.3)
    fig.add_hline(y=100, line_dash="dot", line_color="white", opacity=0.3)

    # Quadrant labels
    for label, x, y in [
        ("Leading",   102, 102), ("Improving", 98, 102),
        ("Lagging",    98,  98), ("Weakening", 102,  98),
    ]:
        fig.add_annotation(x=x, y=y, text=label, showarrow=False,
                            font=dict(size=11, color=colors[label]), opacity=0.5)

    fig.update_layout(
        template="plotly_dark", title="Relative Rotation Graph (RRG)",
        xaxis_title="RS-Ratio", yaxis_title="RS-Momentum",
        height=500, margin=dict(t=50, b=30, l=50, r=20),
    )
    return fig


def ad_bar_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df["sector"], y=df["advance"], name="Advance",
                          marker_color="#00C853"))
    fig.add_trace(go.Bar(x=df["sector"], y=df["decline"], name="Decline",
                          marker_color="#D50000"))
    fig.update_layout(barmode="stack", template="plotly_dark",
                       height=360, margin=dict(t=20, b=80, l=10, r=10),
                       xaxis_tickangle=-45)
    return fig
