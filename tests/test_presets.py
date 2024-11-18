"""Tests for filter preset persistence."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_trend.presets import (
    apply_pending_filter_preset,
    capture_filters,
    delete_preset,
    load_presets,
    normalize_preset_name,
    queue_filter_preset,
    upsert_preset,
)


def test_normalize_preset_name() -> None:
    assert normalize_preset_name("  کریپتو و طلا  ") == "کریپتو و طلا"
    with pytest.raises(ValueError):
        normalize_preset_name("   ")
    with pytest.raises(ValueError):
        normalize_preset_name("bad/name")


def test_upsert_load_delete_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "filter_presets.json"
    filters = {
        "normalize_fx": True,
        "markets": ["Bitcoin", "Gold"],
        "calendar": "jalali",
        "time_scope": "last_7_days",
        "start_year": 1402,
        "start_month": 1,
        "end_year": 1405,
        "end_month": 7,
        "aggregation": "daily",
        "show_events": False,
    }
    name = upsert_preset(path, "کریپتو", filters)
    assert name == "کریپتو"
    loaded = load_presets(path)
    assert loaded["کریپتو"]["markets"] == ["Bitcoin", "Gold"]
    assert loaded["کریپتو"]["show_events"] is False
    assert loaded["کریپتو"]["time_scope"] == "last_7_days"

    upsert_preset(path, "کریپتو", {**filters, "aggregation": "monthly"})
    assert load_presets(path)["کریپتو"]["aggregation"] == "monthly"

    assert delete_preset(path, "کریپتو") is True
    assert load_presets(path) == {}
    assert delete_preset(path, "کریپتو") is False


def test_capture_and_apply_pending() -> None:
    state = {
        "normalize_fx": "off",
        "markets": ["ETH", "PAXG"],
        "calendar": "gregorian",
        "time_scope": "this_month",
        "start_year": 2024,
        "start_month": 3,
        "end_year": 2026,
        "end_month": 10,
        "aggregation": "monthly",
        "show_events": True,
    }
    snapshot = capture_filters(state)
    assert snapshot["calendar"] == "gregorian"
    assert snapshot["markets"] == ["ETH", "PAXG"]
    assert snapshot["normalize_fx"] is False
    assert snapshot["time_scope"] == "this_month"

    df = pd.DataFrame(
        {
            "gregorian_year": [2023, 2024, 2025, 2026],
            "jalali_year": [1402, 1403, 1404, 1405],
        }
    )
    target: dict = {
        # Stale relative scope + years, as if the UI was on last_30_days.
        "time_scope": "last_30_days",
        "start_year": 2026,
        "start_month": 9,
        "end_year": 2026,
        "end_month": 10,
        "markets": ["Gold"],
    }
    queue_filter_preset(target, snapshot)
    apply_pending_filter_preset(
        target,
        df=df,
        known_market_ids={"ETH", "PAXG", "Gold"},
    )
    assert target["markets"] == ["ETH", "PAXG"]
    assert target["calendar"] == "gregorian"
    assert target["start_year"] == 2024
    assert target["start_month"] == 3
    assert target["end_year"] == 2026
    assert target["end_month"] == 10
    assert target["aggregation"] == "monthly"
    assert target["normalize_fx"] == "off"
    assert target["time_scope"] == "this_month"
    assert target["_preset_force_time_scope"] == "this_month"
    assert "_pending_filter_preset" not in target


def test_apply_restores_custom_range_without_time_scope_key() -> None:
    """Older bookmarks omit time_scope; restore must still replace the range."""
    df = pd.DataFrame({"jalali_year": [1400, 1401, 1402, 1403, 1404, 1405]})
    state: dict = {
        "time_scope": "last_30_days",
        "start_year": 1405,
        "start_month": 6,
        "end_year": 1405,
        "end_month": 7,
        "markets": ["Bitcoin"],
    }
    queue_filter_preset(
        state,
        {
            "markets": ["Gold"],
            "calendar": "jalali",
            "start_year": 1402,
            "start_month": 1,
            "end_year": 1403,
            "end_month": 6,
            "aggregation": "daily",
            "normalize_fx": True,
            "show_events": True,
        },
    )
    apply_pending_filter_preset(state, df=df, known_market_ids={"Gold", "Bitcoin"})
    assert state["markets"] == ["Gold"]
    assert state["time_scope"] == "custom"
    assert state["_preset_force_time_scope"] == "custom"
    assert state["start_year"] == 1402
    assert state["start_month"] == 1
    assert state["end_year"] == 1403
    assert state["end_month"] == 6


def test_apply_drops_unknown_markets_and_clamps_years() -> None:
    df = pd.DataFrame({"jalali_year": [1400, 1401, 1402], "gregorian_year": [2021, 2022, 2023]})
    state: dict = {}
    queue_filter_preset(
        state,
        {
            "markets": ["Gone", "Gold"],
            "calendar": "jalali",
            "time_scope": "not_a_scope",
            "start_year": 1390,
            "start_month": 0,
            "end_year": 1410,
            "end_month": 15,
            "aggregation": "weird",
            "normalize_fx": True,
            "show_events": True,
        },
    )
    apply_pending_filter_preset(
        state, df=df, known_market_ids={"Gold", "Bitcoin"}
    )
    assert state["markets"] == ["Gold"]
    assert state["start_year"] == 1400
    assert state["end_year"] == 1402
    assert state["start_month"] == 1
    assert state["end_month"] == 12
    assert state["aggregation"] == "daily"
    assert state["time_scope"] == "custom"
