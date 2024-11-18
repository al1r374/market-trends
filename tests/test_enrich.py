"""Tests for calendar enrichment and daily gap filling."""

from __future__ import annotations

import pandas as pd
import pytest

from market_trend.enrich import add_calendar_features, fill_daily_gaps


def test_fill_daily_gaps_marks_real_and_guessed() -> None:
    rows = [
        {"market_id": "Gold", "date_jalali": "1402/01/01", "closing": 100.0},
        {"market_id": "Gold", "date_jalali": "1402/01/03", "closing": 200.0},
        {"market_id": "Dollar", "date_jalali": "1402/01/01", "closing": 50.0},
        {"market_id": "Dollar", "date_jalali": "1402/01/02", "closing": 60.0},
    ]
    enriched = add_calendar_features(pd.DataFrame(rows), filter_date_range=False)
    filled = fill_daily_gaps(enriched)

    gold = filled[filled["market_id"] == "Gold"].sort_values("date_jalali")
    assert list(gold["date_jalali"]) == ["1402/01/01", "1402/01/02", "1402/01/03"]
    assert list(gold["is_real"]) == [True, False, True]
    # Gap avg of bracketing prices: (100 + 200) / 2 = 150
    assert float(gold.loc[~gold["is_real"], "closing"].iloc[0]) == pytest.approx(150.0)

    dollar = filled[filled["market_id"] == "Dollar"].sort_values("date_jalali")
    assert len(dollar) == 2
    assert dollar["is_real"].all()


def test_fill_daily_gaps_uses_each_gap_brackets() -> None:
    rows = [
        {"market_id": "Gold", "date_jalali": "1402/01/01", "closing": 100.0},
        {"market_id": "Gold", "date_jalali": "1402/01/03", "closing": 200.0},
        {"market_id": "Gold", "date_jalali": "1402/01/06", "closing": 50.0},
    ]
    enriched = add_calendar_features(pd.DataFrame(rows), filter_date_range=False)
    filled = fill_daily_gaps(enriched)
    by_date = filled.set_index("date_jalali")["closing"]

    assert float(by_date["1402/01/02"]) == pytest.approx(150.0)  # (100+200)/2
    assert float(by_date["1402/01/04"]) == pytest.approx(125.0)  # (200+50)/2
    assert float(by_date["1402/01/05"]) == pytest.approx(125.0)  # same gap


def test_fill_daily_gaps_empty() -> None:
    empty = pd.DataFrame(columns=["market_id", "date_jalali", "closing"])
    out = fill_daily_gaps(empty)
    assert out.empty
    assert "is_real" in out.columns


def test_fill_daily_gaps_strips_old_guesses_and_refills() -> None:
    rows = [
        {"market_id": "Gold", "date_jalali": "1402/01/01", "closing": 100.0, "is_real": True},
        {
            "market_id": "Gold",
            "date_jalali": "1402/01/02",
            "closing": 999.0,
            "is_real": False,
        },
        {"market_id": "Gold", "date_jalali": "1402/01/03", "closing": 200.0, "is_real": True},
    ]
    enriched = add_calendar_features(pd.DataFrame(rows), filter_date_range=False)
    # Preserve is_real through enrich for this test input.
    enriched["is_real"] = [True, False, True]
    filled = fill_daily_gaps(enriched)
    by_date = filled.set_index("date_jalali")
    assert bool(by_date.loc["1402/01/02", "is_real"]) is False
    assert float(by_date.loc["1402/01/02", "closing"]) == pytest.approx(150.0)
