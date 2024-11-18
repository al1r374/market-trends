"""Pure metric functions over enriched market DataFrames."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _require_columns(df: pd.DataFrame, columns: set[str]) -> None:
    missing = columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")


def coverage_counts(df: pd.DataFrame) -> pd.DataFrame:
    """Count of closing observations per market and jalali year-month."""
    _require_columns(df, {"market_id", "jalali_year_month", "closing"})
    return (
        df.groupby(["market_id", "market_name_fa", "jalali_year_month"], as_index=False)
        .agg(count=("closing", "count"))
        .sort_values(["market_id", "jalali_year_month"])
    )


def coverage_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    counts = coverage_counts(df)
    return counts.pivot(
        index="market_name_fa", columns="jalali_year_month", values="count"
    ).fillna(0)


def correlation_matrix(
    df: pd.DataFrame,
    market_ids: list[str] | None = None,
    *,
    value_col: str = "closing",
) -> pd.DataFrame:
    """Pearson correlation of daily levels (or returns if precomputed) across markets."""
    _require_columns(df, {"market_id", "jalali_date", "market_name_fa", value_col})
    subset = df if not market_ids else df[df["market_id"].isin(market_ids)]
    subset = subset.dropna(subset=[value_col])
    pivot = subset.pivot_table(
        index="jalali_date", columns="market_name_fa", values=value_col, aggfunc="last"
    )
    return pivot.corr()


def period_growth(
    df: pd.DataFrame,
    *,
    group_cols: list[str],
    value_col: str = "closing",
) -> pd.DataFrame:
    """
    Mean closing per group, then pct_change within each market.

    group_cols must start with market_id (or include it) and a period column.
    """
    _require_columns(df, set(group_cols) | {value_col, "market_id", "market_name_fa"})
    grouped = (
        df.groupby(group_cols + ["market_name_fa"], as_index=False)
        .agg(mean_closing=(value_col, "mean"))
        .sort_values(group_cols)
    )
    period_cols = [c for c in group_cols if c != "market_id"]
    grouped["growth_rate"] = (
        grouped.groupby("market_id")["mean_closing"].pct_change() * 100
    )
    return grouped.dropna(subset=["growth_rate"]).reset_index(drop=True)


def yearly_growth(df: pd.DataFrame, calendar: str = "jalali") -> pd.DataFrame:
    year_col = f"{calendar}_year"
    return period_growth(df, group_cols=["market_id", year_col])


def yearly_ranks(df: pd.DataFrame, calendar: str = "jalali") -> pd.DataFrame:
    growth = yearly_growth(df, calendar=calendar)
    year_col = f"{calendar}_year"
    growth["rank"] = growth.groupby(year_col)["growth_rate"].rank(
        ascending=False, method="dense"
    )
    return growth.sort_values([year_col, "rank"])


def mean_yearly_rank(df: pd.DataFrame, calendar: str = "jalali", exclude_years: list[int] | None = None) -> pd.DataFrame:
    ranks = yearly_ranks(df, calendar=calendar)
    year_col = f"{calendar}_year"
    if exclude_years:
        ranks = ranks[~ranks[year_col].isin(exclude_years)]
    return (
        ranks.groupby(["market_id", "market_name_fa"], as_index=False)
        .agg(mean_rank=("rank", "mean"), mean_growth=("growth_rate", "mean"))
        .sort_values("mean_rank")
    )


def seasonal_growth(df: pd.DataFrame, calendar: str = "jalali") -> pd.DataFrame:
    year_col = f"{calendar}_year"
    season_col = f"{calendar}_season"
    return period_growth(df, group_cols=["market_id", year_col, season_col])


def monthly_growth(df: pd.DataFrame, calendar: str = "jalali") -> pd.DataFrame:
    year_col = f"{calendar}_year"
    month_col = f"{calendar}_month"
    return period_growth(df, group_cols=["market_id", year_col, month_col])


def multi_year_growth(df: pd.DataFrame, width: int = 2, calendar: str = "jalali") -> pd.DataFrame:
    if width not in (2, 3, 4):
        raise ValueError("width must be 2, 3, or 4")
    period_col = f"{calendar}_{width}_year_period"
    return period_growth(df, group_cols=["market_id", period_col])


def daily_returns(df: pd.DataFrame) -> pd.DataFrame:
    _require_columns(df, {"market_id", "jalali_date", "closing", "market_name_fa"})
    ordered = df.sort_values(["market_id", "jalali_date"]).copy()
    ordered["daily_return"] = ordered.groupby("market_id")["closing"].pct_change()
    return ordered.dropna(subset=["daily_return"])


def volatility_ranking(df: pd.DataFrame) -> pd.DataFrame:
    returns = daily_returns(df)
    return (
        returns.groupby(["market_id", "market_name_fa"], as_index=False)
        .agg(
            volatility=("daily_return", "std"),
            mean_return=("daily_return", "mean"),
            observations=("daily_return", "count"),
        )
        .sort_values("volatility")
    )


def max_drawdown_series(prices: pd.Series) -> float:
    cumulative_max = prices.cummax()
    drawdown = prices / cumulative_max - 1.0
    return float(drawdown.min()) if len(drawdown) else np.nan


DEFAULT_FX_MARKET_ID = "USDT"


def build_fx_by_date(
    fx_df: pd.DataFrame,
    *,
    dates: pd.Series | None = None,
) -> pd.Series:
    """IRR-per-USDT map keyed by ``date_jalali``, forward-filled onto ``dates``."""
    _require_columns(fx_df, {"date_jalali", "closing", "jalali_date"})
    ordered = (
        fx_df.dropna(subset=["closing"])
        .sort_values("jalali_date")
        .drop_duplicates(subset=["date_jalali"], keep="last")
    )
    series = pd.Series(
        ordered["closing"].astype(float).to_numpy(),
        index=ordered["date_jalali"].astype(str),
        name="fx_irr_per_usdt",
    )
    if dates is None or len(dates) == 0:
        return series
    idx = pd.Index(sorted(set(dates.astype(str))))
    # Forward-fill only — do not invent USDT rates before the series starts.
    return series.reindex(idx).ffill()


def prices_in_numeraire(
    df: pd.DataFrame,
    *,
    numeraire: str = "native",
    fx_by_date: pd.Series | None = None,
    currency_by_id: dict[str, str] | None = None,
    fx_market_id: str = DEFAULT_FX_MARKET_ID,
) -> pd.DataFrame:
    """
    Add ``value`` column: closing expressed in the chosen numeraire.

    - native: raw closing
    - irr: USD-quoted markets × USDT (IRR); IRR markets unchanged
    - usd: IRR-quoted markets ÷ USDT; USD markets unchanged

    Rows without a usable USDT rate are set to NaN (including IRR markets),
    so every series is clipped to FX coverage.
    """
    _require_columns(df, {"market_id", "date_jalali", "closing"})
    if numeraire not in {"native", "irr", "usd"}:
        raise ValueError(f"Unsupported numeraire: {numeraire}")

    out = df.copy()
    out["closing"] = pd.to_numeric(out["closing"], errors="coerce")
    currencies = currency_by_id or {}

    if numeraire == "native":
        out["value"] = out["closing"]
        return out

    if fx_by_date is None or fx_by_date.empty:
        raise ValueError("نرخ تتر برای نرمال‌سازی ارزی در دسترس نیست")

    fx = out["date_jalali"].astype(str).map(fx_by_date)
    values = np.full(len(out), np.nan, dtype=float)

    for i, (market_id, rate, close) in enumerate(
        zip(out["market_id"], fx, out["closing"], strict=True)
    ):
        if pd.isna(close) or close <= 0:
            continue
        if market_id == fx_market_id:
            # USDT series is IRR per 1 USDT.
            values[i] = float(close) if numeraire == "irr" else 1.0
            continue
        quote = currencies.get(str(market_id))
        if quote not in {"irr", "usd"}:
            # Unknown quote currency — do not guess (guessing IRR under-converts crypto).
            continue
        if pd.isna(rate) or rate <= 0:
            continue
        if numeraire == "irr":
            values[i] = float(close) * float(rate) if quote == "usd" else float(close)
        else:  # usd / USDT terms
            values[i] = float(close) / float(rate) if quote == "irr" else float(close)

    out["value"] = values
    return out


def indexed_growth_series(
    df: pd.DataFrame,
    *,
    value_col: str = "closing",
    date_col: str = "date",
    align_period: bool = True,
    exclude_market_ids: list[str] | None = None,
) -> pd.DataFrame:
    """
    Cumulative percent growth from each market's first price in the window.

    When ``align_period`` is True and multiple markets are present, all series
    share the same overlapping date range so relative growth is comparable.
    """
    _require_columns(df, {"market_id", "market_name_fa", value_col, date_col})
    empty = pd.DataFrame(
        columns=["market_id", "market_name_fa", date_col, value_col, "growth_pct"]
    )
    working = df.copy()
    if exclude_market_ids:
        working = working[~working["market_id"].isin(exclude_market_ids)]
    working[value_col] = pd.to_numeric(working[value_col], errors="coerce")
    working = working.dropna(subset=[value_col])
    working = working[working[value_col].astype(float) > 0]
    working[date_col] = working[date_col].astype(str)

    series_by_market: dict[str, pd.DataFrame] = {}
    for market_id, group in working.groupby("market_id"):
        g = group.sort_values(date_col)
        if len(g) < 2:
            continue
        series_by_market[str(market_id)] = g

    if not series_by_market:
        return empty

    common_start = None
    common_end = None
    if align_period and len(series_by_market) > 1:
        common_start = max(g[date_col].iloc[0] for g in series_by_market.values())
        common_end = min(g[date_col].iloc[-1] for g in series_by_market.values())
        # No shared window across all selected markets — keep each series on
        # its own baseline instead of wiping the whole chart.
        if common_start >= common_end:
            common_start = None
            common_end = None

    frames: list[pd.DataFrame] = []
    for market_id, g in series_by_market.items():
        if common_start is not None and common_end is not None:
            g = g[(g[date_col] >= common_start) & (g[date_col] <= common_end)]
        if len(g) < 2:
            continue
        out = g.copy()
        base = float(out[value_col].iloc[0])
        out["growth_pct"] = (out[value_col].astype(float) / base - 1.0) * 100.0
        frames.append(out)

    if not frames:
        return empty
    return pd.concat(frames, ignore_index=True)


def selected_period_growth(
    df: pd.DataFrame,
    *,
    numeraire: str = "native",
    fx_df: pd.DataFrame | None = None,
    currency_by_id: dict[str, str] | None = None,
    fx_market_id: str = DEFAULT_FX_MARKET_ID,
    align_period: bool = True,
    exclude_fx_market: bool = True,
) -> pd.DataFrame:
    """
    Percent growth from first to last price in ``df``, per market.

    With ``numeraire`` ``irr``/``usd``, prices are FX-adjusted via USDT
    (IRR per tether) before measuring growth. When ``align_period`` is True,
    all markets use the same overlapping calendar window.
    """
    _require_columns(df, {"market_id", "jalali_date", "closing", "market_name_fa"})
    if numeraire != "native":
        if fx_df is None or fx_df.empty:
            raise ValueError("نرخ تتر برای نرمال‌سازی ارزی در دسترس نیست")
        fx_by_date = build_fx_by_date(fx_df, dates=df["date_jalali"])
        working = prices_in_numeraire(
            df,
            numeraire=numeraire,
            fx_by_date=fx_by_date,
            currency_by_id=currency_by_id,
            fx_market_id=fx_market_id,
        )
    else:
        working = df.copy()
        working["value"] = pd.to_numeric(working["closing"], errors="coerce")

    series_by_market: dict[str, pd.DataFrame] = {}
    for market_id, group in working.sort_values("jalali_date").groupby("market_id"):
        if exclude_fx_market and numeraire != "native" and market_id == fx_market_id:
            continue
        g = group.dropna(subset=["value"]).copy()
        g = g[g["value"].astype(float) > 0]
        if len(g) < 2:
            continue
        g = g.sort_values("jalali_date")
        series_by_market[str(market_id)] = g

    if not series_by_market:
        return pd.DataFrame(
            columns=[
                "market_id",
                "market_name_fa",
                "growth_pct",
                "start_price",
                "end_price",
                "start_date",
                "end_date",
                "observations",
                "numeraire",
                "quote_currency",
            ]
        )

    common_start = None
    common_end = None
    if align_period and len(series_by_market) > 1:
        common_start = max(g["date_jalali"].astype(str).iloc[0] for g in series_by_market.values())
        common_end = min(g["date_jalali"].astype(str).iloc[-1] for g in series_by_market.values())
        if common_start >= common_end:
            common_start = None
            common_end = None

    rows: list[dict] = []
    for market_id, g in series_by_market.items():
        dates = g["date_jalali"].astype(str)
        if common_start is not None and common_end is not None:
            g = g[(dates >= common_start) & (dates <= common_end)]
            if len(g) < 2:
                continue
        start = g.iloc[0]
        end = g.iloc[-1]
        start_price = float(start["value"])
        end_price = float(end["value"])
        start_date = str(start["date_jalali"])
        end_date = str(end["date_jalali"])
        rows.append(
            {
                "market_id": market_id,
                "market_name_fa": start["market_name_fa"],
                "growth_pct": (end_price / start_price - 1.0) * 100,
                "start_price": start_price,
                "end_price": end_price,
                "start_date": start_date,
                "end_date": end_date,
                "observations": int(len(g)),
                "numeraire": numeraire,
                "quote_currency": (currency_by_id or {}).get(market_id, ""),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "market_id",
                "market_name_fa",
                "growth_pct",
                "start_price",
                "end_price",
                "start_date",
                "end_date",
                "observations",
                "numeraire",
                "quote_currency",
            ]
        )
    return pd.DataFrame(rows).sort_values("growth_pct", ascending=False).reset_index(
        drop=True
    )


def risk_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Peak return, total return, worst drawdown, and volatility per market."""
    _require_columns(df, {"market_id", "jalali_date", "closing", "market_name_fa"})
    rows: list[dict] = []
    for market_id, group in df.sort_values("jalali_date").groupby("market_id"):
        closes = group["closing"].astype(float)
        closes = closes[closes > 0]
        if len(closes) < 2:
            continue
        start = float(closes.iloc[0])
        total_return = float(closes.iloc[-1] / start - 1.0)
        peak_return = float(closes.max() / start - 1.0)
        drawdown = max_drawdown_series(closes)
        vol = float(closes.pct_change().std())
        rows.append(
            {
                "market_id": market_id,
                "market_name_fa": group["market_name_fa"].iloc[0],
                "total_return_pct": total_return * 100,
                "peak_return_pct": peak_return * 100,
                "max_drawdown_pct": drawdown * 100,
                "volatility": vol,
                "start_price": start,
                "end_price": float(closes.iloc[-1]),
                "peak_price": float(closes.max()),
            }
        )
    return pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)


def conditional_up_markets(
    df: pd.DataFrame,
    *,
    anchor_ids: list[str],
) -> pd.DataFrame:
    """
    When all anchor markets have negative daily returns, average return of other markets.
    """
    returns = daily_returns(df)
    pivot = returns.pivot_table(
        index="jalali_date", columns="market_id", values="daily_return", aggfunc="last"
    )
    missing_anchors = [a for a in anchor_ids if a not in pivot.columns]
    if missing_anchors:
        raise ValueError(f"Anchor markets not in data: {missing_anchors}")

    mask = (pivot[anchor_ids] < 0).all(axis=1)
    down_days = pivot.loc[mask]
    if down_days.empty:
        return pd.DataFrame(columns=["market_id", "mean_return_pct", "observations"])

    others = [c for c in down_days.columns if c not in anchor_ids]
    summary = down_days[others].mean().rename("mean_return").reset_index()
    summary.columns = ["market_id", "mean_return"]
    summary["mean_return_pct"] = summary["mean_return"] * 100
    summary["observations"] = mask.sum()
    name_map = (
        df[["market_id", "market_name_fa"]]
        .drop_duplicates()
        .set_index("market_id")["market_name_fa"]
    )
    summary["market_name_fa"] = summary["market_id"].map(name_map)
    return summary.sort_values("mean_return_pct", ascending=False)


def seasonality_snapshot(
    df: pd.DataFrame,
    *,
    market_id: str,
    calendar: str = "jalali",
) -> pd.DataFrame:
    """
    Historical mean growth by month/season vs the latest period for one market.
    """
    subset = df[df["market_id"] == market_id]
    if subset.empty:
        return pd.DataFrame()

    month_col = f"{calendar}_month"
    month_name_col = f"{calendar}_month_name"
    growth = monthly_growth(subset, calendar=calendar)
    if growth.empty:
        return growth

    historical = (
        growth.groupby(month_col, as_index=False)
        .agg(hist_mean_growth=("growth_rate", "mean"), hist_std=("growth_rate", "std"))
    )
    latest_year = growth[f"{calendar}_year"].max()
    latest = growth[growth[f"{calendar}_year"] == latest_year][
        [month_col, "growth_rate"]
    ].rename(columns={"growth_rate": "latest_growth"})
    merged = historical.merge(latest, on=month_col, how="left")
    merged["delta_vs_hist"] = merged["latest_growth"] - merged["hist_mean_growth"]
    merged["market_id"] = market_id

    name_lookup = (
        subset[[month_col, month_name_col]]
        .drop_duplicates()
        .set_index(month_col)[month_name_col]
        if month_name_col in subset.columns
        else None
    )
    if name_lookup is not None:
        merged["month_name"] = merged[month_col].map(name_lookup)
    else:
        from market_trend.config import month_name as resolve_month_name

        merged["month_name"] = merged[month_col].map(
            lambda m: resolve_month_name(m, calendar)
        )

    return merged.sort_values(month_col)


def top_n_yearly(df: pd.DataFrame, n: int = 5, calendar: str = "jalali") -> pd.DataFrame:
    growth = yearly_growth(df, calendar=calendar)
    year_col = f"{calendar}_year"
    return (
        growth.sort_values([year_col, "growth_rate"], ascending=[True, False])
        .groupby(year_col, group_keys=False)
        .head(n)
        .reset_index(drop=True)
    )
