"""Unit tests for market_data upsert uniqueness."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from market_trend.db import (
    cleanup_market_data,
    ensure_schema,
    normalize_jalali_str,
    upsert_prices,
)


def test_normalize_jalali_str_pads_and_accepts_dash() -> None:
    assert normalize_jalali_str("1402/1/5") == "1402/01/05"
    assert normalize_jalali_str("1402-01-05") == "1402/01/05"
    assert normalize_jalali_str("-") is None
    assert normalize_jalali_str(None) is None


def test_upsert_dedupes_same_symbol_same_day(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    ensure_schema(conn)

    frame = pd.DataFrame(
        [
            {
                "market_id": "Dollar",
                "date_jalali": "1402/1/5",
                "date_gregorian": "2023-03-25",
                "closing": 100.0,
            },
            {
                "market_id": "Dollar",
                "date_jalali": "1402/01/05",
                "date_gregorian": "2023-03-25",
                "closing": 110.0,
            },
            {
                "market_id": "Dollar",
                "date_jalali": "1402/01/06",
                "date_gregorian": "2023-03-26",
                "closing": 120.0,
            },
        ]
    )
    written = upsert_prices(frame, source="test", conn=conn)
    assert written == 2

    rows = conn.execute(
        "SELECT date_jalali, closing FROM market_data WHERE market_id = ? ORDER BY date_jalali",
        ("Dollar",),
    ).fetchall()
    assert rows == [("1402/01/05", 110.0), ("1402/01/06", 120.0)]

    # Unique index: market_id + date_gregorian
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(market_data)").fetchall()
    }
    assert "idx_market_data_market_gregorian" in indexes
    conn.close()


def test_cleanup_collapses_format_variants(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    # Legacy table: PK allows mixed jalali formats for the same day.
    conn.executescript(
        """
        CREATE TABLE market_data (
            market_id TEXT NOT NULL,
            date_jalali TEXT NOT NULL,
            date_gregorian TEXT,
            closing REAL NOT NULL,
            source TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (market_id, date_jalali)
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO market_data
            (market_id, date_jalali, date_gregorian, closing, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("Gold", "1402/1/5", "2023-03-25", 1.0, "old", "2020-01-01T00:00:00+00:00"),
            ("Gold", "1402/01/05", "2023-03-25", 2.0, "new", "2024-01-01T00:00:00+00:00"),
            ("Gold", "1402/01/06", "2023-03-26", 3.0, "new", "2024-01-01T00:00:00+00:00"),
        ],
    )
    stats = cleanup_market_data(conn=conn)
    assert stats["before"] == 3
    assert stats["after"] == 2
    assert stats["removed"] == 1
    rows = conn.execute(
        "SELECT date_jalali, closing FROM market_data ORDER BY date_jalali"
    ).fetchall()
    assert rows == [("1402/01/05", 2.0), ("1402/01/06", 3.0)]
    conn.close()
