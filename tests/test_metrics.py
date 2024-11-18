"""Smoke tests for enrich and metrics."""

from __future__ import annotations

import pandas as pd
import pytest
from persiantools.jdatetime import JalaliDate

from market_trend.config import load_config, normalize_market_id
from market_trend.enrich import add_calendar_features, aggregate_prices
from market_trend.metrics import (
    correlation_matrix,
    indexed_growth_series,
    risk_summary,
    selected_period_growth,
    yearly_growth,
    yearly_ranks,
)


@pytest.fixture
def sample_frame() -> pd.DataFrame:
    rows = []
    for market_id, base in (("Gold", 100.0), ("Dollar", 50.0)):
        for year, month, day, bump in (
            (1400, 1, 1, 0),
            (1400, 6, 1, 10),
            (1401, 1, 1, 20),
            (1401, 6, 1, 30),
            (1402, 1, 1, 40),
        ):
            rows.append(
                {
                    "market_id": market_id,
                    "date_jalali": f"{year}/{month:02d}/{day:02d}",
                    "closing": base + bump,
                }
            )
    return pd.DataFrame(rows)


def test_normalize_doje_alias() -> None:
    assert normalize_market_id("Doje") == "Doge"
    assert normalize_market_id("Doge") == "Doge"


def test_load_config_has_markets() -> None:
    cfg = load_config()
    assert cfg.db_path.name == "market_data.db"
    assert any(m.id == "Doge" for m in cfg.markets)
    assert not any(m.id == "Doje" for m in cfg.markets)


def test_month_names_both_calendars(sample_frame: pd.DataFrame) -> None:
    from market_trend.config import month_name, month_options

    assert month_name(1, "jalali") == "فروردین"
    assert month_name(12, "jalali") == "اسفند"
    assert month_name(1, "gregorian") == "ژانویه"
    assert month_name(12, "gregorian") == "دسامبر"
    assert len(month_options("jalali")) == 12
    assert len(month_options("gregorian")) == 12

    enriched = add_calendar_features(sample_frame, filter_date_range=False)
    assert "jalali_month_name" in enriched.columns
    assert "gregorian_month_name" in enriched.columns
    assert enriched["jalali_month_name"].iloc[0] == "فروردین"


def test_add_calendar_features(sample_frame: pd.DataFrame) -> None:
    enriched = add_calendar_features(sample_frame, filter_date_range=False)
    assert "jalali_year" in enriched.columns
    assert "gregorian_date" in enriched.columns
    assert "market_name_fa" in enriched.columns
    assert enriched["jalali_season"].notna().all()
    assert isinstance(enriched["jalali_date"].iloc[0], JalaliDate)



def test_aggregate_monthly(sample_frame: pd.DataFrame) -> None:
    enriched = add_calendar_features(sample_frame, filter_date_range=False)
    monthly = aggregate_prices(enriched, aggregation="monthly")
    assert set(monthly.columns) >= {"market_id", "date", "closing"}
    assert len(monthly) == len(sample_frame)


def test_yearly_growth_and_ranks(sample_frame: pd.DataFrame) -> None:
    enriched = add_calendar_features(sample_frame, filter_date_range=False)
    growth = yearly_growth(enriched)
    assert "growth_rate" in growth.columns
    assert growth["growth_rate"].notna().all()
    ranks = yearly_ranks(enriched)
    assert "rank" in ranks.columns


def test_correlation_and_risk(sample_frame: pd.DataFrame) -> None:
    enriched = add_calendar_features(sample_frame, filter_date_range=False)
    corr = correlation_matrix(enriched)
    assert corr.shape[0] == corr.shape[1]
    summary = risk_summary(enriched)
    assert set(["total_return_pct", "max_drawdown_pct", "peak_return_pct"]).issubset(
        summary.columns
    )
    assert len(summary) == 2


def test_indexed_growth_series(sample_frame: pd.DataFrame) -> None:
    enriched = add_calendar_features(sample_frame, filter_date_range=False)
    agg = aggregate_prices(enriched, calendar="jalali", aggregation="daily")
    series = indexed_growth_series(agg, date_col="date")
    assert set(series["market_id"]) == {"Gold", "Dollar"}
    # Aligned window starts at first common date; both start at 0%.
    starts = series.groupby("market_id").first()
    assert (starts["growth_pct"] == 0.0).all()
    ends = series.groupby("market_id").last()["growth_pct"]
    assert ends["Gold"] == pytest.approx(40.0)
    assert ends["Dollar"] == pytest.approx(80.0)


def test_indexed_growth_falls_back_when_no_common_window() -> None:
    rows = [
        {"market_id": "Old", "date_jalali": "1402/01/01", "closing": 100.0},
        {"market_id": "Old", "date_jalali": "1402/01/02", "closing": 110.0},
        {"market_id": "New", "date_jalali": "1403/01/01", "closing": 50.0},
        {"market_id": "New", "date_jalali": "1403/01/02", "closing": 75.0},
    ]
    enriched = add_calendar_features(pd.DataFrame(rows), filter_date_range=False)
    agg = aggregate_prices(enriched, calendar="jalali", aggregation="daily")
    series = indexed_growth_series(agg, date_col="date", align_period=True)
    assert set(series["market_id"]) == {"Old", "New"}
    ends = series.groupby("market_id").last()["growth_pct"]
    assert ends["Old"] == pytest.approx(10.0)
    assert ends["New"] == pytest.approx(50.0)


def test_selected_period_growth(sample_frame: pd.DataFrame) -> None:
    enriched = add_calendar_features(sample_frame, filter_date_range=False)
    growth = selected_period_growth(enriched)
    assert set(growth["market_id"]) == {"Gold", "Dollar"}
    # Gold: 100 -> 140 = +40%; Dollar: 50 -> 90 = +80%
    by_id = growth.set_index("market_id")["growth_pct"]
    assert by_id["Gold"] == pytest.approx(40.0)
    assert by_id["Dollar"] == pytest.approx(80.0)
    assert growth.iloc[0]["market_id"] == "Dollar"


def test_selected_period_growth_fx_numeraire() -> None:
    rows = []
    # USDT doubles; USD-gold flat in USD → doubles in IRR; IRR fund tracks USDT×gold.
    for day, usdt, paxg_usd, fund_irr in (
        (1, 100.0, 10.0, 1000.0),
        (2, 150.0, 10.0, 1500.0),
        (3, 200.0, 10.0, 2000.0),
    ):
        date = f"1402/01/{day:02d}"
        rows.extend(
            [
                {"market_id": "USDT", "date_jalali": date, "closing": usdt},
                {"market_id": "PAXG", "date_jalali": date, "closing": paxg_usd},
                {"market_id": "Sandoghe-Aiar", "date_jalali": date, "closing": fund_irr},
            ]
        )
    frame = pd.DataFrame(rows)
    enriched = add_calendar_features(frame, filter_date_range=False)
    currency = {"USDT": "irr", "PAXG": "usd", "Sandoghe-Aiar": "irr"}
    fx = enriched[enriched["market_id"] == "USDT"]

    native = selected_period_growth(enriched, currency_by_id=currency)
    native_pct = native.set_index("market_id")["growth_pct"]
    assert native_pct["PAXG"] == pytest.approx(0.0)
    assert native_pct["Sandoghe-Aiar"] == pytest.approx(100.0)

    irr = selected_period_growth(
        enriched,
        numeraire="irr",
        fx_df=fx,
        currency_by_id=currency,
        fx_market_id="USDT",
    )
    # USDT (FX) excluded from comparison table.
    assert "USDT" not in set(irr["market_id"])
    irr_pct = irr.set_index("market_id")["growth_pct"]
    assert irr_pct["PAXG"] == pytest.approx(100.0)
    assert irr_pct["Sandoghe-Aiar"] == pytest.approx(100.0)
    assert set(irr["start_date"]) == {"1402/01/01"}
    assert set(irr["end_date"]) == {"1402/01/03"}

    usd = selected_period_growth(
        enriched,
        numeraire="usd",
        fx_df=fx,
        currency_by_id=currency,
        fx_market_id="USDT",
    )
    usd_pct = usd.set_index("market_id")["growth_pct"]
    assert usd_pct["PAXG"] == pytest.approx(0.0)
    assert usd_pct["Sandoghe-Aiar"] == pytest.approx(0.0)


def test_selected_period_growth_aligns_common_window() -> None:
    rows = []
    # Aiar missing early days; PAXG missing late days → common window is middle.
    for day, usdt, paxg, aiar in (
        (1, 100.0, 10.0, None),
        (2, 100.0, 11.0, 1000.0),
        (3, 100.0, 12.0, 1100.0),
        (4, 100.0, None, 1200.0),
    ):
        date = f"1402/02/{day:02d}"
        rows.append({"market_id": "USDT", "date_jalali": date, "closing": usdt})
        if paxg is not None:
            rows.append({"market_id": "PAXG", "date_jalali": date, "closing": paxg})
        if aiar is not None:
            rows.append(
                {"market_id": "Sandoghe-Aiar", "date_jalali": date, "closing": aiar}
            )
    enriched = add_calendar_features(pd.DataFrame(rows), filter_date_range=False)
    currency = {"USDT": "irr", "PAXG": "usd", "Sandoghe-Aiar": "irr"}
    fx = enriched[enriched["market_id"] == "USDT"]
    growth = selected_period_growth(
        enriched,
        numeraire="irr",
        fx_df=fx,
        currency_by_id=currency,
    )
    # Common window: 1402/02/02 → 1402/02/03
    assert set(growth["start_date"]) == {"1402/02/02"}
    assert set(growth["end_date"]) == {"1402/02/03"}
    by_id = growth.set_index("market_id")["growth_pct"]
    assert by_id["PAXG"] == pytest.approx((12 / 11 - 1) * 100)
    assert by_id["Sandoghe-Aiar"] == pytest.approx(10.0)


def test_missing_currency_map_does_not_treat_crypto_as_irr() -> None:
    rows = [
        {"market_id": "USDT", "date_jalali": "1402/03/01", "closing": 100.0},
        {"market_id": "USDT", "date_jalali": "1402/03/02", "closing": 200.0},
        {"market_id": "PAXG", "date_jalali": "1402/03/01", "closing": 10.0},
        {"market_id": "PAXG", "date_jalali": "1402/03/02", "closing": 10.0},
    ]
    enriched = add_calendar_features(pd.DataFrame(rows), filter_date_range=False)
    fx = enriched[enriched["market_id"] == "USDT"]
    growth = selected_period_growth(
        enriched, numeraire="irr", fx_df=fx, currency_by_id={}
    )
    assert growth.empty
