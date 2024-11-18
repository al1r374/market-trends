"""Unit tests for ETL fetch parsers."""

from __future__ import annotations

from market_trend.etl.fetchers import (
    _finalize_price_frame,
    _normalize_gregorian,
    _parse_abantether_line_chart,
    _parse_binance_klines,
    _parse_coinlore_hdata,
    _parse_tgju_table,
)
import pandas as pd


def test_parse_tgju_tether_irr() -> None:
    raw = {
        "data": [
            [
                "2,668,060",
                "2,667,890",
                "2,679,300",
                "2,668,060",
                "-",
                "-",
                "2026/10/09",
                "1405/07/17",
            ]
        ]
    }
    df = _parse_tgju_table(raw, "USDT", "tgju_indicator")
    assert len(df) == 1
    assert df.iloc[0]["date_jalali"] == "1405/07/17"
    assert df.iloc[0]["date_gregorian"] == "2026-10-09"
    assert abs(float(df.iloc[0]["closing"]) - 2_668_060.0) < 1e-6


def test_parse_tgju_indicator_keeps_gregorian() -> None:
    raw = {
        "data": [
            [
                "0.00001234",
                "0.00001100",
                "0.00001300",
                "0.00001250",
                "-",
                "-",
                "2024/01/15",
                "1402/10/25",
            ]
        ]
    }
    df = _parse_tgju_table(raw, "Shiba", "tgju_indicator")
    assert len(df) == 1
    assert df.iloc[0]["date_jalali"] == "1402/10/25"
    assert df.iloc[0]["date_gregorian"] == "2024-01-15"
    assert abs(float(df.iloc[0]["closing"]) - 0.0000125) < 1e-12


def test_parse_binance_klines_preserves_precision() -> None:
    # 2024-01-15 00:00:00 UTC
    open_time_ms = 1_705_276_800_000
    raw = [[open_time_ms, "0", "0", "0", "0.00001234", "0", 0, "0", 0, "0", "0", "0"]]
    df = _parse_binance_klines(raw, "Shiba")
    assert len(df) == 1
    assert df.iloc[0]["date_gregorian"] == "2024-01-15"
    assert df.iloc[0]["date_jalali"] == "1402/10/25"
    assert abs(float(df.iloc[0]["closing"]) - 0.00001234) < 1e-14


def test_normalize_gregorian() -> None:
    assert _normalize_gregorian("2024/01/15") == "2024-01-15"
    assert _normalize_gregorian("2024-01-15") == "2024-01-15"
    assert _normalize_gregorian("-") is None
    assert _normalize_gregorian(None) is None


def test_finalize_price_frame_dedupes_same_day() -> None:
    df = pd.DataFrame(
        [
            {
                "market_id": "Gold",
                "date_jalali": "1402/1/5",
                "date_gregorian": "2023-03-25",
                "closing": 1.0,
            },
            {
                "market_id": "Gold",
                "date_jalali": "1402/01/05",
                "date_gregorian": "2023-03-25",
                "closing": 2.0,
            },
        ]
    )
    out = _finalize_price_frame(df)
    assert len(out) == 1
    assert out.iloc[0]["date_jalali"] == "1402/01/05"
    assert float(out.iloc[0]["closing"]) == 2.0


def test_parse_tgju_dedupes_duplicate_days() -> None:
    raw = {
        "data": [
            ["1402/10/25", "100", "90", "110"],
            ["1402/10/25", "105", "90", "110"],
        ]
    }
    df = _parse_tgju_table(raw, "Bourse", "tgju_index")
    assert len(df) == 1
    assert float(df.iloc[0]["closing"]) == 105.0


def test_parse_abantether_line_chart_uses_tehran_date() -> None:
    # 2025-10-09 20:30:00 UTC == 2025-10-10 00:00 Asia/Tehran
    raw = {
        "symbol": "AST_HMBOX",
        "interval": "yearly",
        "points": [
            [1_760_041_800, "11050.00623444914"],
            [1_760_128_200, "10380.005856432766"],
        ],
    }
    df = _parse_abantether_line_chart(raw, "HomeBox")
    assert len(df) == 2
    assert df.iloc[0]["date_gregorian"] == "2025-10-10"
    assert df.iloc[0]["date_jalali"] == "1404/07/18"
    assert abs(float(df.iloc[0]["closing"]) - 11050.00623444914) < 1e-9


def test_parse_abantether_line_chart_dedupes_intraday() -> None:
    # Two points on the same Tehran calendar day → keep last close.
    raw = {
        "points": [
            [1_791_560_400, "18130.0"],  # 2026-10-09 15:40 UTC
            [1_791_564_000, "18200.0"],  # same Tehran day, later
        ],
    }
    df = _parse_abantether_line_chart(raw, "HomeBox")
    assert len(df) == 1
    assert float(df.iloc[0]["closing"]) == 18200.0


def test_parse_coinlore_hdata_uses_utc_date() -> None:
    # 2026-01-08 23:59:59 UTC end-of-day bar → 2026-01-08
    raw = {
        "price": [
            [1_767_916_799_000, 69.444071748275],
            [1_768_003_199_000, 70.585855243325],
        ]
    }
    df = _parse_coinlore_hdata(raw, "USOON")
    assert len(df) == 2
    assert df.iloc[0]["date_gregorian"] == "2026-01-08"
    assert df.iloc[0]["date_jalali"] == "1404/10/18"
    assert abs(float(df.iloc[0]["closing"]) - 69.444071748275) < 1e-9


def test_parse_coinlore_hdata_dedupes_intraday() -> None:
    # Hourly points on the same UTC day → keep last close.
    raw = {
        "price": [
            [1_791_709_200_000, 149.0],  # 2026-10-11 08:00 UTC
            [1_791_712_800_000, 148.5],  # 2026-10-11 09:00 UTC
        ]
    }
    df = _parse_coinlore_hdata(raw, "USOON")
    assert len(df) == 1
    assert df.iloc[0]["date_gregorian"] == "2026-10-11"
    assert float(df.iloc[0]["closing"]) == 148.5
