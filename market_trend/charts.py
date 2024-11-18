"""Plotly chart builders (return figures; never call .show())."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from market_trend.config import AppConfig, get_config


FONT_FAMILY = "IRANSans-Edit, Tahoma, sans-serif"
# Absolute prices (e.g. BTC in IRR vs fund NAVs) need log scale past this span.
LOG_Y_MIN_SPAN_RATIO = 100.0
# Integer prices with thousands separator (e.g. 265,931,000).
PRICE_TICKFORMAT = ",.0f"
PRICE_HOVERFORMAT = ",.0f"


def _layout(fig: go.Figure, title: str, config: AppConfig | None = None) -> go.Figure:
    cfg = config or get_config()
    fig.update_layout(
        title=title,
        template=cfg.chart_template,
        height=cfg.chart_height,
        margin=dict(l=40, r=40, t=60, b=40),
        legend_title_text="",
        font=dict(family=FONT_FAMILY),
        title_font=dict(family=FONT_FAMILY),
    )
    return fig


def _apply_price_axis(fig: go.Figure) -> None:
    """Thousand-separated tick + hover labels on price Y axes."""
    fig.update_yaxes(tickformat=PRICE_TICKFORMAT, hoverformat=PRICE_HOVERFORMAT)


def price_trend(
    df: pd.DataFrame,
    *,
    date_col: str = "date",
    color_map: dict[str, str] | None = None,
    title: str = "روند قیمت",
    calendar: str = "jalali",
    config: AppConfig | None = None,
) -> go.Figure:
    plot_df = df.copy()
    if "market_name_fa" not in plot_df.columns:
        plot_df["market_name_fa"] = plot_df["market_id"]

    # Always use plain strings so Plotly does not reinterpret Jalali as Gregorian dates.
    plot_df[date_col] = plot_df[date_col].astype(str)
    if "date_sort" in plot_df.columns:
        plot_df = plot_df.sort_values(["market_id", "date_sort"])
    else:
        plot_df = plot_df.sort_values(["market_id", date_col])

    fig = px.line(
        plot_df,
        x=date_col,
        y="closing",
        color="market_name_fa",
        color_discrete_map=color_map or {},
        labels={"closing": "قیمت پایانی", date_col: "تاریخ", "market_name_fa": "بازار"},
        category_orders={
            date_col: list(dict.fromkeys(plot_df[date_col].tolist()))
        },
    )
    # Category axis keeps Jalali labels (e.g. 1403/05/01) from being parsed as Miladi.
    fig.update_xaxes(type="category", tickangle=45)
    positives = pd.to_numeric(plot_df["closing"], errors="coerce")
    positives = positives[positives > 0]
    if len(positives) and positives.max() / positives.min() >= LOG_Y_MIN_SPAN_RATIO:
        fig.update_yaxes(type="log")
    _apply_price_axis(fig)
    if calendar == "jalali":
        fig.update_layout(xaxis_title="تاریخ شمسی")
    else:
        fig.update_layout(xaxis_title="تاریخ میلادی")
    return _layout(fig, title, config)


def growth_trend(
    df: pd.DataFrame,
    *,
    date_col: str = "date",
    color_map: dict[str, str] | None = None,
    title: str = "مقایسه رشد",
    calendar: str = "jalali",
    config: AppConfig | None = None,
) -> go.Figure:
    plot_df = df.copy()
    if "market_name_fa" not in plot_df.columns:
        plot_df["market_name_fa"] = plot_df["market_id"]

    plot_df[date_col] = plot_df[date_col].astype(str)
    if "date_sort" in plot_df.columns:
        plot_df = plot_df.sort_values(["market_id", "date_sort"])
    else:
        plot_df = plot_df.sort_values(["market_id", date_col])

    fig = px.line(
        plot_df,
        x=date_col,
        y="growth_pct",
        color="market_name_fa",
        color_discrete_map=color_map or {},
        labels={
            "growth_pct": "رشد ٪",
            date_col: "تاریخ",
            "market_name_fa": "بازار",
        },
        category_orders={
            date_col: list(dict.fromkeys(plot_df[date_col].tolist()))
        },
    )
    fig.update_xaxes(type="category", tickangle=45)
    fig.add_hline(y=0, line_dash="dot", line_color="#888888", opacity=0.6)
    if calendar == "jalali":
        fig.update_layout(xaxis_title="تاریخ شمسی", yaxis_title="رشد ٪")
    else:
        fig.update_layout(xaxis_title="تاریخ میلادی", yaxis_title="رشد ٪")
    return _layout(fig, title, config)


def price_trend_with_events(
    price_df: pd.DataFrame,
    events_df: pd.DataFrame,
    *,
    date_col: str = "date",
    calendar: str = "jalali",
    color_map: dict[str, str] | None = None,
    title: str = "روند قیمت و رویدادها",
    config: AppConfig | None = None,
) -> go.Figure:
    fig = price_trend(
        price_df,
        date_col=date_col,
        calendar=calendar,
        color_map=color_map,
        title=title,
        config=config,
    )
    if events_df is None or events_df.empty or price_df.empty:
        return fig

    if calendar != "jalali":
        # Event dates are stored as Jalali year/month; skip overlay on Miladi axis.
        return fig

    y_max = float(price_df["closing"].max())
    event_points_x: list[str] = []
    event_points_text: list[str] = []
    dates = price_df[date_col].astype(str)
    for _, event in events_df.iterrows():
        key = str(event["date_jalali"]).replace("-", "/")
        matches = dates[dates.str.startswith(key)]
        if matches.empty:
            continue
        event_points_x.append(matches.iloc[0])
        event_points_text.append(str(event["event"]))

    if event_points_x:
        fig.add_trace(
            go.Scatter(
                x=event_points_x,
                y=[y_max * 0.98] * len(event_points_x),
                mode="markers",
                name="رویداد",
                marker=dict(symbol="diamond", size=10, color="#C0392B"),
                text=event_points_text,
                hovertemplate="%{text}<extra></extra>",
            )
        )
    return fig


def coverage_heatmap(heatmap: pd.DataFrame, title: str = "پوشش داده", config: AppConfig | None = None) -> go.Figure:
    fig = px.imshow(
        heatmap,
        aspect="auto",
        color_continuous_scale="Viridis",
        labels=dict(x="سال-ماه", y="بازار", color="تعداد"),
    )
    fig.update_xaxes(tickangle=90)
    return _layout(fig, title, config)


def correlation_heatmap(corr: pd.DataFrame, title: str = "همبستگی بازارها", config: AppConfig | None = None) -> go.Figure:
    fig = px.imshow(
        corr,
        text_auto=".2f",
        color_continuous_scale="RdBu",
        zmin=-1,
        zmax=1,
        labels=dict(color="همبستگی"),
    )
    return _layout(fig, title, config)


def stacked_growth_bars(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str = "growth_rate",
    color_col: str = "market_name_fa",
    title: str = "نرخ رشد",
    config: AppConfig | None = None,
) -> go.Figure:
    fig = px.bar(
        df,
        x=x_col,
        y=y_col,
        color=color_col,
        barmode="group",
        text=y_col,
        labels={y_col: "رشد ٪", x_col: x_col, color_col: "بازار"},
    )
    fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
    return _layout(fig, title, config)


def rank_heatmap(
    ranks: pd.DataFrame,
    *,
    year_col: str = "jalali_year",
    title: str = "رتبه سالانه بازارها",
    config: AppConfig | None = None,
) -> go.Figure:
    rank_pivot = ranks.pivot(index="market_name_fa", columns=year_col, values="rank")
    growth_pivot = ranks.pivot(index="market_name_fa", columns=year_col, values="growth_rate")
    fig = px.imshow(
        rank_pivot,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="YlOrRd_r",
        labels=dict(x="سال", y="بازار", color="رتبه"),
    )
    fig.update_traces(
        customdata=growth_pivot.reindex(index=rank_pivot.index, columns=rank_pivot.columns).values,
        hovertemplate="بازار: %{y}<br>سال: %{x}<br>رتبه: %{z}<br>رشد: %{customdata:.1f}%<extra></extra>",
    )
    fig.update_yaxes(autorange="reversed")
    return _layout(fig, title, config)


def monthly_subplots(
    df: pd.DataFrame,
    *,
    market_name: str,
    calendar: str = "jalali",
    title: str | None = None,
    config: AppConfig | None = None,
) -> go.Figure:
    from market_trend.config import months_for_calendar

    cfg = config or get_config()
    year_col = f"{calendar}_year"
    month_col = f"{calendar}_month"
    month_name_col = f"{calendar}_month_name"

    group_cols = [year_col, month_col]
    if month_name_col in df.columns:
        group_cols.append(month_name_col)

    monthly = df.groupby(group_cols, as_index=False).agg(avg_closing=("closing", "mean"))
    monthly = monthly.sort_values([year_col, month_col])
    years = sorted(monthly[year_col].unique())
    cols = 2
    rows = max(1, (len(years) + 1) // 2)
    month_labels = list(months_for_calendar(calendar))

    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=[f"سال {year}" for year in years],
    )
    for idx, year in enumerate(years):
        yearly = monthly[monthly[year_col] == year].copy()
        if month_name_col in yearly.columns:
            x_values = yearly[month_name_col]
        else:
            x_values = yearly[month_col].astype(int).map(lambda m: month_labels[m - 1])
        row = idx // cols + 1
        col = idx % cols + 1
        fig.add_trace(
            go.Scatter(
                x=x_values,
                y=yearly["avg_closing"],
                mode="lines+markers",
                name=str(year),
                showlegend=False,
            ),
            row=row,
            col=col,
        )
        fig.update_xaxes(
            categoryorder="array",
            categoryarray=month_labels,
            row=row,
            col=col,
        )
    _apply_price_axis(fig)
    fig.update_layout(
        title=title or f"میانگین ماهانه — {market_name}",
        template=cfg.chart_template,
        height=max(cfg.chart_height, 280 * rows),
        font=dict(family=FONT_FAMILY),
        title_font=dict(family=FONT_FAMILY),
    )
    return fig


def bar_ranking(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    title: str,
    color_col: str | None = None,
    config: AppConfig | None = None,
) -> go.Figure:
    fig = px.bar(
        df,
        x=x_col,
        y=y_col,
        color=color_col,
        orientation="h" if y_col.endswith("fa") or y_col == "market_name_fa" else "v",
        labels={x_col: x_col, y_col: y_col},
    )
    return _layout(fig, title, config)


def horizontal_metric_bars(
    df: pd.DataFrame,
    *,
    metric: str,
    title: str,
    config: AppConfig | None = None,
    diverging: bool = False,
) -> go.Figure:
    ordered = df.sort_values(metric)
    if diverging:
        marker_colors = [
            "#2ca02c" if float(v) >= 0 else "#d62728" for v in ordered[metric]
        ]
        fig = go.Figure(
            data=[
                go.Bar(
                    x=ordered[metric],
                    y=ordered["market_name_fa"],
                    orientation="h",
                    marker_color=marker_colors,
                    text=[f"{float(v):+.1f}%" for v in ordered[metric]],
                    textposition="outside",
                    hovertemplate="%{y}: %{x:+.2f}%<extra></extra>",
                )
            ]
        )
        fig.update_layout(
            xaxis_title="رشد ٪",
            yaxis_title="بازار",
            showlegend=False,
        )
    else:
        fig = px.bar(
            ordered,
            x=metric,
            y="market_name_fa",
            orientation="h",
            labels={metric: metric, "market_name_fa": "بازار"},
        )
    return _layout(fig, title, config)
