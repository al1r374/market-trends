"""Tests for relative time-scope date ranges."""

from __future__ import annotations

from datetime import date

from market_trend.time_scopes import resolve_time_scope


def test_custom_returns_none() -> None:
    assert resolve_time_scope("custom") is None


def test_last_7_days_inclusive() -> None:
    today = date(2026, 10, 12)
    range_ = resolve_time_scope("last_7_days", today=today)
    assert range_ is not None
    assert range_.start == date(2026, 10, 6)
    assert range_.end == today


def test_this_week_jalali_starts_saturday() -> None:
    # 2026-10-12 is Monday → week start Sat 2026-10-10
    today = date(2026, 10, 12)
    range_ = resolve_time_scope("this_week", calendar="jalali", today=today)
    assert range_ is not None
    assert range_.start == date(2026, 10, 10)
    assert range_.end == today


def test_this_week_gregorian_starts_monday() -> None:
    today = date(2026, 10, 12)
    range_ = resolve_time_scope("this_week", calendar="gregorian", today=today)
    assert range_ is not None
    assert range_.start == date(2026, 10, 12)
    assert range_.end == today


def test_last_week_jalali() -> None:
    today = date(2026, 10, 12)
    range_ = resolve_time_scope("last_week", calendar="jalali", today=today)
    assert range_ is not None
    assert range_.start == date(2026, 10, 3)
    assert range_.end == date(2026, 10, 9)


def test_this_month_jalali() -> None:
    # 2026-10-12 ≈ 1405/07/20 → Mehr starts ~2026-09-23
    today = date(2026, 10, 12)
    range_ = resolve_time_scope("this_month", calendar="jalali", today=today)
    assert range_ is not None
    assert range_.end == today
    assert range_.start < today


def test_all_uses_data_bounds() -> None:
    range_ = resolve_time_scope(
        "all",
        today=date(2026, 10, 12),
        data_min=date(2020, 1, 1),
        data_max=date(2026, 9, 1),
    )
    assert range_ is not None
    assert range_.start == date(2020, 1, 1)
    assert range_.end == date(2026, 9, 1)


def test_clamp_to_data_max() -> None:
    today = date(2026, 10, 12)
    range_ = resolve_time_scope(
        "last_30_days",
        today=today,
        data_min=date(2020, 1, 1),
        data_max=date(2026, 10, 1),
    )
    assert range_ is not None
    assert range_.end == date(2026, 10, 1)
    assert range_.start == date(2026, 9, 2)
