"""Tests for events.csv load/append helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_trend.config import AppConfig, MarketConfig
from market_trend.db import append_event, load_events, normalize_event_date


def _cfg(events_path: Path) -> AppConfig:
    return AppConfig(
        db_path=events_path.parent / "unused.db",
        events_path=events_path,
        presets_path=events_path.parent / "filter_presets.json",
        start_jalali="1395/01/01",
        end_jalali="1410/01/01",
        chart_height=600,
        chart_template="plotly_white",
        markets=(
            MarketConfig(
                id="Gold",
                fa_name="طلا",
                color="#FFD700",
                category="gold",
                enabled=True,
                source="test",
                url="",
                currency="irr",
            ),
        ),
    )


def test_normalize_event_date() -> None:
    assert normalize_event_date("1402/1") == "1402/01"
    assert normalize_event_date("1402-01-05") == "1402/01/05"
    assert normalize_event_date("bad") is None


def test_append_event_creates_and_loads(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    cfg = _cfg(path)
    saved = append_event(
        "1403/2",
        "اعتراضات آزمایشی",
        ["protest"],
        config=cfg,
    )
    assert saved["date_jalali"] == "1403/02"
    assert saved["tags"] == "protest"

    append_event("1403/03", "برجام آزمایشی", config=cfg)
    events = load_events(config=cfg)
    assert len(events) == 2
    inferred = events.loc[events["event"] == "برجام آزمایشی", "tags"].iloc[0]
    assert "sanctions" in inferred

    raw = pd.read_csv(path)
    assert list(raw.columns) == ["Date", "Event", "tags"]
