"""Sector -> Stock network diagram (Plotly + networkx spring layout).

Tree: "NSE Market" root -> sector nodes -> stock leaf nodes, drawn like a
language-family cluster map. Each sector's stocks share one color; node size
scales with market cap / index weight when sector_intelligence data is passed.
"""
from __future__ import annotations

import math

import networkx as nx
import plotly.graph_objects as go

ROOT = "NSE Market"

# 21 visually-distinct colors (dark-theme friendly)
_PALETTE = [
    "#42A5F5", "#66BB6A", "#FFA726", "#EC407A", "#AB47BC", "#26C6DA",
    "#FFEE58", "#8D6E63", "#78909C", "#5C6BC0", "#EF5350", "#9CCC65",
    "#FF7043", "#29B6F6", "#D4E157", "#7E57C2", "#26A69A", "#FFCA28",
    "#F06292", "#00E5FF", "#CDDC39",
]


def _spring_positions(sector_stocks: dict[str, list[str]]) -> dict:
    g = nx.Graph()
    g.add_node(ROOT)
    for sec, syms in sector_stocks.items():
        g.add_edge(ROOT, sec)
        for s in syms:
            g.add_edge(sec, f"{sec}::{s}")   # sector-prefix: stocks may repeat across sectors
    return nx.spring_layout(g, k=0.9 / math.sqrt(max(g.number_of_nodes(), 1)),
                            iterations=120, seed=42), g


def build_network_figure(
    sector_stocks: dict[str, list[str]],
    stock_info: dict[tuple[str, str], dict] | None = None,
    selected_sector: str | None = None,
    height: int = 720,
    show_stock_labels: bool = False,
) -> go.Figure:
    """stock_info: {(sector, symbol_no_ns): {weight, mcap, name}} — optional sizing/hover data."""
    if selected_sector and selected_sector in sector_stocks:
        sector_stocks = {selected_sector: sector_stocks[selected_sector]}
    stock_info = stock_info or {}

    pos, g = _spring_positions(sector_stocks)

    # Edges — one trace
    ex, ey = [], []
    for a, b in g.edges():
        ex += [pos[a][0], pos[b][0], None]
        ey += [pos[a][1], pos[b][1], None]
    fig = go.Figure(go.Scatter(
        x=ex, y=ey, mode="lines", hoverinfo="skip", showlegend=False,
        line=dict(color="rgba(140,150,170,0.35)", width=1),
    ))

    single = len(sector_stocks) == 1
    label_stocks = single or show_stock_labels
    sec_mcaps = {}
    for sec, syms in sector_stocks.items():
        sec_mcaps[sec] = sum((stock_info.get((sec, s.replace(".NS", ""))) or {}).get("mcap", 0) or 0
                             for s in syms)
    max_sec_mcap = max(sec_mcaps.values()) or 1

    for i, (sec, syms) in enumerate(sector_stocks.items()):
        color = _PALETTE[i % len(_PALETTE)]
        xs, ys, sizes, texts, hovers = [], [], [], [], []

        # sector hub node first
        xs.append(pos[sec][0]); ys.append(pos[sec][1])
        sizes.append(22 + 14 * (sec_mcaps[sec] / max_sec_mcap))
        texts.append(f"<b>{sec}</b>")
        hovers.append(f"<b>{sec}</b><br>{len(syms)} stocks"
                      + (f"<br>Mkt cap: ₹{sec_mcaps[sec]:,.0f} Cr" if sec_mcaps[sec] else ""))

        weights = [(stock_info.get((sec, s.replace('.NS', ''))) or {}) for s in syms]
        max_w = max((w.get("weight") or 0) for w in weights) or 1
        for s, info in zip(syms, weights):
            node = f"{sec}::{s}"
            tick = s.replace(".NS", "")
            xs.append(pos[node][0]); ys.append(pos[node][1])
            w = info.get("weight") or 0
            sizes.append(8 + 14 * (w / max_w) if w else 9)
            texts.append(tick if label_stocks else "")
            h = f"<b>{tick}</b><br>Sector: {sec}"
            if info.get("name"):
                h += f"<br>{info['name']}"
            if w:
                h += f"<br>Index weight: {w:.1f}%"
            if info.get("mcap"):
                h += f"<br>Mkt cap: ₹{info['mcap']:,.0f} Cr"
            hovers.append(h)

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text", name=sec,
            marker=dict(size=sizes, color=color, line=dict(color="#0e1117", width=1)),
            text=texts, textposition="top center",
            textfont=dict(size=10 if single else 8, color="#d1d4dc"),
            hovertext=hovers, hoverinfo="text",
        ))

    # root node (whole-market view only)
    if not single:
        fig.add_trace(go.Scatter(
            x=[pos[ROOT][0]], y=[pos[ROOT][1]], mode="markers+text", showlegend=False,
            marker=dict(size=44, color="#1E88E5", line=dict(color="#90CAF9", width=2)),
            text=["<b>NSE Market</b>"], textposition="middle center",
            textfont=dict(size=11, color="#fff"),
            hoverinfo="skip",
        ))

    fig.update_layout(
        template="plotly_dark", height=height,
        showlegend=not single,
        legend=dict(font=dict(size=10), itemsizing="constant"),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(t=20, b=20, l=20, r=20),
        hovermode="closest",
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig
