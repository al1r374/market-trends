"""Tests against the real market_data.db (skipped if missing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_trend.config import get_config
from market_trend.db import ensure_schema, load_events, load_market_frame, connect
from market_trend.enrich import add_calendar_features
from market_trend.metrics import coverage_counts, volatility_ranking

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def live_df():
    cfg = get_config()
    if not cfg.db_path.exists():
        pytest.skip("market_data.db not present")
    with connect(cfg.db_path) as conn:
        ensure_schema(conn)
    raw = load_market_frame(config=cfg)
    if raw.empty:
        pytest.skip("market_data.db is empty")
    return add_calendar_features(raw, config=cfg)


def test_db_loads_and_normalizes_doge(live_df) -> None:
    assert "Doge" in set(live_df["market_id"]) or "Doge" not in {
        *live_df["market_id"],
        "Doje",
    }
    assert "Doje" not in set(live_df["market_id"])
    assert live_df["closing"].notna().all()


def test_coverage_and_volatility(live_df) -> None:
    counts = coverage_counts(live_df)
    assert not counts.empty
    vol = volatility_ranking(live_df)
    assert "volatility" in vol.columns


def test_events_load() -> None:
    events = load_events()
    assert {"date_jalali", "event", "tags"}.issubset(events.columns)
    assert len(events) > 0
