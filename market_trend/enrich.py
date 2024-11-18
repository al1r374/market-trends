"""Calendar feature engineering for market price frames."""

from __future__ import annotations

import pandas as pd
from persiantools.jdatetime import JalaliDate

from market_trend.config import (
    GREGORIAN_SEASONS,
    JALALI_SEASONS,
    AppConfig,
    get_config,
    month_name,
    resolve_fa_name,
)


def parse_jalali_string(value: str) -> JalaliDate:
    year, month, day = (int(part) for part in str(value).split("/")[:3])
    return JalaliDate(year, month, day)


def jalali_to_str(date: JalaliDate) -> str:
    return f"{date.year:04d}/{date.month:02d}/{date.day:02d}"


def _season_index(month: int) -> int:
    return (int(month) - 1) // 3


def _period_label(year: int, width: int) -> str:
    start = (year // width) * width
    return "-".join(str(y) for y in range(start, start + width))


def add_calendar_features(
    df: pd.DataFrame,
    *,
    config: AppConfig | None = None,
    filter_date_range: bool = True,
) -> pd.DataFrame:
    """
    Add jalali/gregorian calendar columns.

    Expects columns: market_id, date_jalali, closing.
    """
    if df.empty:
        return df.copy()

    cfg = config or get_config()
    out = df.copy()
    out["date_jalali"] = out["date_jalali"].astype(str)

    parts = out["date_jalali"].str.split("/", expand=True)
    out["jalali_year"] = parts[0].astype(int)
    out["jalali_month"] = parts[1].str.zfill(2)
    out["jalali_day"] = parts[2].str.zfill(2) if parts.shape[1] > 2 else "01"
    out["jalali_year_month"] = (
        out["jalali_year"].astype(str) + "-" + out["jalali_month"]
    )
    out["jalali_season"] = out["jalali_month"].astype(int).map(
        lambda m: JALALI_SEASONS[_season_index(m)]
    )
    out["jalali_month_name"] = out["jalali_month"].astype(int).map(
        lambda m: month_name(m, "jalali")
    )

    jalali_objects = [
        JalaliDate(int(y), int(m), int(d))
        for y, m, d in zip(out["jalali_year"], out["jalali_month"], out["jalali_day"])
    ]
    out["jalali_date"] = jalali_objects
    out["jalali_week_day"] = [d.strftime("%A") for d in jalali_objects]

    gregorian = [d.to_gregorian() for d in jalali_objects]
    out["gregorian_date"] = pd.to_datetime(gregorian)
    out["date_gregorian"] = out["gregorian_date"].dt.strftime("%Y-%m-%d")
    out["gregorian_year"] = out["gregorian_date"].dt.year
    out["gregorian_month"] = out["gregorian_date"].dt.strftime("%m")
    out["gregorian_year_month"] = out["gregorian_date"].dt.strftime("%Y-%m")
    out["gregorian_season"] = out["gregorian_date"].dt.month.map(
        lambda m: GREGORIAN_SEASONS[_season_index(m)]
    )
    out["gregorian_month_name"] = out["gregorian_date"].dt.month.map(
        lambda m: month_name(m, "gregorian")
    )
    out["gregorian_week_day"] = out["gregorian_date"].dt.day_name()

    for width in (2, 3, 4):
        out[f"jalali_{width}_year_period"] = out["jalali_year"].map(
            lambda y, w=width: _period_label(y, w)
        )
        out[f"gregorian_{width}_year_period"] = out["gregorian_year"].map(
            lambda y, w=width: _period_label(y, w)
        )

    out["market_name_fa"] = out["market_id"].map(lambda mid: resolve_fa_name(mid, cfg))

    if filter_date_range:
        start = parse_jalali_string(cfg.start_jalali)
        end = parse_jalali_string(cfg.end_jalali)
        out = out[(out["jalali_date"] >= start) & (out["jalali_date"] < end)]

    return out.reset_index(drop=True)


def filter_markets(df: pd.DataFrame, market_ids: list[str] | None) -> pd.DataFrame:
    if not market_ids:
        return df
    return df[df["market_id"].isin(market_ids)].copy()


def fill_daily_gaps(
    df: pd.DataFrame,
    *,
    config: AppConfig | None = None,
) -> pd.DataFrame:
    """
    Fill missing calendar days that sit strictly between two real priced days.

    Prior guessed rows (``is_real=False``) are dropped first. Each interior gap
    between consecutive real observations is filled with
    ``(start_price + end_price) / 2``. Days before the first or after the last
    real price are never invented. Guessed rows are flagged ``is_real=False``.
    """
    if df.empty:
        out = df.copy()
        out["is_real"] = pd.Series(dtype=bool)
        return out

    required = {"market_id", "date_jalali", "closing"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"fill_daily_gaps missing columns: {sorted(missing)}")

    cfg = config or get_config()
    # Always rebuild from real observations only.
    working = df.copy()
    if "is_real" in working.columns:
        working = working[working["is_real"].fillna(True)].drop(columns=["is_real"])

    frames: list[pd.DataFrame] = []
    for market_id, group in working.groupby("market_id", sort=False):
        g = group.copy()
        g["closing"] = pd.to_numeric(g["closing"], errors="coerce")
        g = g.dropna(subset=["closing"])
        if g.empty:
            continue

        if "gregorian_date" in g.columns:
            g["gregorian_date"] = pd.to_datetime(g["gregorian_date"])
        else:
            jalali_dates = [parse_jalali_string(v) for v in g["date_jalali"].astype(str)]
            g["gregorian_date"] = pd.to_datetime([d.to_gregorian() for d in jalali_dates])

        real = (
            g.sort_values("gregorian_date")
            .drop_duplicates(subset=["gregorian_date"], keep="last")
            .loc[:, ["gregorian_date", "closing"]]
            .reset_index(drop=True)
        )

        rows: list[dict] = [
            {
                "market_id": market_id,
                "date_jalali": jalali_to_str(
                    JalaliDate.to_jalali(pd.Timestamp(ts).date())
                ),
                "closing": float(price),
                "is_real": True,
            }
            for ts, price in zip(real["gregorian_date"], real["closing"], strict=True)
        ]

        # Only fill calendar days strictly inside each consecutive real pair.
        for i in range(len(real) - 1):
            start_ts = pd.Timestamp(real.iloc[i]["gregorian_date"])
            end_ts = pd.Timestamp(real.iloc[i + 1]["gregorian_date"])
            gap_days = int((end_ts - start_ts).days) - 1
            if gap_days <= 0:
                continue
            gap_price = (
                float(real.iloc[i]["closing"]) + float(real.iloc[i + 1]["closing"])
            ) / 2.0
            for offset in range(1, gap_days + 1):
                ts = start_ts + pd.Timedelta(days=offset)
                rows.append(
                    {
                        "market_id": market_id,
                        "date_jalali": jalali_to_str(
                            JalaliDate.to_jalali(ts.date())
                        ),
                        "closing": gap_price,
                        "is_real": False,
                    }
                )

        frames.append(pd.DataFrame(rows))

    if not frames:
        out = df.iloc[0:0].copy()
        out["is_real"] = pd.Series(dtype=bool)
        return out

    slim = pd.concat(frames, ignore_index=True)
    enriched = add_calendar_features(slim, config=cfg, filter_date_range=False)
    enriched["is_real"] = slim["is_real"].astype(bool).to_numpy()
    return enriched.sort_values(["market_id", "date_jalali"]).reset_index(drop=True)


def aggregate_prices(
    df: pd.DataFrame,
    *,
    calendar: str = "jalali",
    aggregation: str = "daily",
) -> pd.DataFrame:
    """Aggregate to daily or monthly mean closing with calendar-aware date labels."""
    if df.empty:
        return df

    if aggregation == "daily":
        if calendar == "jalali":
            out = df[["market_id", "market_name_fa", "closing", "date_jalali"]].copy()
            out["date"] = out["date_jalali"].astype(str)
            out["date_sort"] = out["date"]
        else:
            out = df[["market_id", "market_name_fa", "closing", "date_gregorian"]].copy()
            out["date"] = out["date_gregorian"].astype(str)
            out["date_sort"] = out["date"]
        return out.sort_values(["market_id", "date_sort"]).drop(columns=["date_sort"], errors="ignore")

    year_col = f"{calendar}_year"
    month_col = f"{calendar}_month"
    month_name_col = f"{calendar}_month_name"
    period_col = f"{calendar}_year_month"

    group_cols = ["market_id", "market_name_fa", period_col, year_col, month_col]
    if month_name_col in df.columns:
        group_cols.append(month_name_col)

    grouped = (
        df.groupby(group_cols, as_index=False)
        .agg(closing=("closing", "mean"))
        .sort_values(["market_id", period_col])
    )
    if month_name_col in grouped.columns:
        grouped["date"] = (
            grouped[year_col].astype(str) + "/" + grouped[month_name_col].astype(str)
        )
    else:
        grouped["date"] = grouped[period_col].astype(str)
    return grouped[["market_id", "market_name_fa", "date", "closing", period_col]].rename(
        columns={period_col: "date_sort"}
    )
