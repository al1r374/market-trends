"""SQLite access, schema migration, and data loading."""

from __future__ import annotations

import csv
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from persiantools.jdatetime import JalaliDate

from market_trend.config import AppConfig, get_config, normalize_market_id

logger = logging.getLogger(__name__)

# Sources that fully replace a market's history on each successful fetch.
REPLACE_MARKET_SOURCES = frozenset(
    {"binance_klines", "abantether_line_chart", "coinlore_hdata"}
)


def normalize_jalali_str(date_jalali: object) -> str | None:
    """Canonical `YYYY/MM/DD` Jalali, or None if unparseable."""
    if date_jalali is None or (isinstance(date_jalali, float) and pd.isna(date_jalali)):
        return None
    text = str(date_jalali).strip().replace("-", "/")
    if not text or text.lower() in {"none", "nan", "-"}:
        return None
    try:
        year, month, day = (int(part) for part in text.split("/")[:3])
        return f"{year:04d}/{month:02d}/{day:02d}"
    except (TypeError, ValueError, OverflowError):
        return None


def jalali_to_gregorian_str(date_jalali: str) -> str | None:
    """Convert `YYYY/MM/DD` Jalali to `YYYY-MM-DD` Gregorian."""
    normalized = normalize_jalali_str(date_jalali)
    if normalized is None:
        return None
    try:
        year, month, day = (int(part) for part in normalized.split("/")[:3])
        gregorian = JalaliDate(year, month, day).to_gregorian()
        return gregorian.strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_data (
    market_id TEXT NOT NULL,
    date_jalali TEXT NOT NULL,
    date_gregorian TEXT,
    closing REAL NOT NULL,
    source TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (market_id, date_jalali)
);
CREATE INDEX IF NOT EXISTS idx_market_data_gregorian
    ON market_data (date_gregorian);
CREATE INDEX IF NOT EXISTS idx_market_data_market
    ON market_data (market_id);
"""

UNIQUE_DAY_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_market_data_market_gregorian
    ON market_data (market_id, date_gregorian)
    WHERE date_gregorian IS NOT NULL AND date_gregorian != '';
"""

LEGACY_COLUMNS = {"id", "jalali_date", "market_type", "closing"}
NEW_COLUMNS = {"market_id", "date_jalali", "date_gregorian", "closing", "source", "updated_at"}


@contextmanager
def connect(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    cfg = get_config()
    path = Path(db_path) if db_path else cfg.db_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table: str = "market_data") -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _ensure_unique_day_index(conn: sqlite3.Connection) -> bool:
    """Create unique (market_id, date_gregorian) index when data allows it."""
    try:
        conn.executescript(UNIQUE_DAY_INDEX_SQL)
        return True
    except sqlite3.IntegrityError:
        logger.warning(
            "Duplicate market/day rows block unique gregorian index; "
            "run cleanup_market_data()"
        )
        return False


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate market_data to the canonical schema."""
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "market_data" not in tables:
        conn.executescript(SCHEMA_SQL)
        _ensure_unique_day_index(conn)
        logger.info("Created market_data schema")
        return

    columns = _table_columns(conn)
    if NEW_COLUMNS.issubset(columns) and "market_type" not in columns:
        conn.executescript(SCHEMA_SQL)
        _ensure_unique_day_index(conn)
        return

    if LEGACY_COLUMNS.issubset(columns):
        _migrate_legacy(conn)
        return

    conn.executescript(SCHEMA_SQL)
    _ensure_unique_day_index(conn)


def _migrate_legacy(conn: sqlite3.Connection) -> None:
    logger.info("Migrating legacy market_data schema")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS market_data_new (
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
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT market_type, jalali_date, closing FROM market_data "
        "WHERE closing IS NOT NULL"
    ).fetchall()

    upserts: list[tuple[str, str, float, str]] = []
    for market_type, jalali_date, closing in rows:
        market_id = normalize_market_id(str(market_type))
        upserts.append((market_id, str(jalali_date), float(closing), now))

    conn.executemany(
        """
        INSERT INTO market_data_new (market_id, date_jalali, closing, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(market_id, date_jalali) DO UPDATE SET
            closing = excluded.closing,
            updated_at = excluded.updated_at
        """,
        upserts,
    )
    conn.execute("DROP TABLE market_data")
    conn.execute("ALTER TABLE market_data_new RENAME TO market_data")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_market_data_gregorian
            ON market_data (date_gregorian);
        CREATE INDEX IF NOT EXISTS idx_market_data_market
            ON market_data (market_id);
        """
    )
    _ensure_unique_day_index(conn)
    logger.info("Migrated %s rows to new schema", len(upserts))


def delete_market_prices(
    market_id: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Delete all rows for one market. Returns deleted row count."""
    normalized = normalize_market_id(market_id)

    def _run(active: sqlite3.Connection) -> int:
        ensure_schema(active)
        cursor = active.execute(
            "DELETE FROM market_data WHERE market_id = ?",
            (normalized,),
        )
        return int(cursor.rowcount)

    if conn is None:
        with connect() as owned:
            return _run(owned)
    return _run(conn)


def backfill_gregorian_dates(
    *,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Fill null date_gregorian from date_jalali. Returns updated row count."""

    def _run(active: sqlite3.Connection) -> int:
        ensure_schema(active)
        rows = active.execute(
            """
            SELECT market_id, date_jalali
            FROM market_data
            WHERE date_gregorian IS NULL OR date_gregorian = ''
            """
        ).fetchall()
        updates = []
        for market_id, date_jalali in rows:
            gregorian = jalali_to_gregorian_str(date_jalali)
            if gregorian:
                updates.append((gregorian, market_id, date_jalali))
        if updates:
            active.executemany(
                """
                UPDATE market_data
                SET date_gregorian = ?
                WHERE market_id = ? AND date_jalali = ?
                """,
                updates,
            )
        return len(updates)

    if conn is None:
        with connect() as owned:
            return _run(owned)
    return _run(conn)


def cleanup_market_data(
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """Normalize dates and keep one row per market per day. Returns counts."""

    def _run(active: sqlite3.Connection) -> dict[str, int]:
        ensure_schema(active)
        before = int(
            active.execute("SELECT COUNT(*) FROM market_data").fetchone()[0]
        )
        df = pd.read_sql_query(
            """
            SELECT market_id, date_jalali, date_gregorian, closing, source, updated_at
            FROM market_data
            ORDER BY market_id, date_jalali, updated_at
            """,
            active,
        )
        if df.empty:
            return {"before": 0, "after": 0, "removed": 0, "normalized": 0}

        original_jalali = df["date_jalali"].astype(str)
        df["date_jalali"] = df["date_jalali"].map(normalize_jalali_str)
        normalized = int(
            (df["date_jalali"].notna() & (df["date_jalali"] != original_jalali)).sum()
        )
        df["closing"] = pd.to_numeric(df["closing"], errors="coerce")
        df = df.dropna(subset=["market_id", "date_jalali", "closing"])

        def _norm_g(value: object) -> str | None:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            text = str(value).strip().replace("/", "-")[:10]
            return text or None

        df["date_gregorian"] = df["date_gregorian"].map(_norm_g)
        missing = df["date_gregorian"].isna()
        if missing.any():
            df.loc[missing, "date_gregorian"] = df.loc[missing, "date_jalali"].map(
                jalali_to_gregorian_str
            )

        # Prefer latest updated_at when collapsing same-day rows.
        df = df.sort_values(
            ["market_id", "date_jalali", "updated_at"], kind="mergesort"
        )
        df = df.drop_duplicates(subset=["market_id", "date_jalali"], keep="last")
        has_g = df["date_gregorian"].notna() & (df["date_gregorian"].astype(str) != "")
        if has_g.any():
            with_g = df.loc[has_g].drop_duplicates(
                subset=["market_id", "date_gregorian"], keep="last"
            )
            df = pd.concat([df.loc[~has_g], with_g], ignore_index=True)

        now = datetime.now(timezone.utc).isoformat()
        df["updated_at"] = df["updated_at"].fillna(now)
        if "source" not in df.columns:
            df["source"] = None

        records = [
            (
                str(row["market_id"]),
                str(row["date_jalali"]),
                None
                if pd.isna(row["date_gregorian"])
                else str(row["date_gregorian"]),
                float(row["closing"]),
                None if pd.isna(row["source"]) else row["source"],
                str(row["updated_at"]),
            )
            for _, row in df.iterrows()
        ]
        active.execute("DELETE FROM market_data")
        active.executemany(
            """
            INSERT INTO market_data
                (market_id, date_jalali, date_gregorian, closing, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        after = int(active.execute("SELECT COUNT(*) FROM market_data").fetchone()[0])
        indexed = _ensure_unique_day_index(active)
        return {
            "before": before,
            "after": after,
            "removed": before - after,
            "normalized": normalized,
            "unique_day_index": int(indexed),
        }

    if conn is None:
        with connect() as owned:
            return _run(owned)
    return _run(conn)


def upsert_prices(
    df: pd.DataFrame,
    *,
    source: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Upsert rows with columns market_id, date_jalali, closing [, date_gregorian]."""
    if df.empty:
        return 0

    required = {"market_id", "date_jalali", "closing"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"upsert_prices missing columns: {sorted(missing)}")

    payload = df.copy()
    payload["market_id"] = payload["market_id"].map(normalize_market_id)
    payload["date_jalali"] = payload["date_jalali"].map(normalize_jalali_str)
    payload["closing"] = pd.to_numeric(payload["closing"], errors="coerce")
    payload = payload.dropna(subset=["market_id", "date_jalali", "closing"])
    if "date_gregorian" not in payload.columns:
        payload["date_gregorian"] = None

    def _normalize_row_gregorian(value: object) -> str | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        if not text or text.lower() in {"none", "nan"}:
            return None
        return text.replace("/", "-")[:10]

    payload["date_gregorian"] = payload["date_gregorian"].map(_normalize_row_gregorian)
    missing_gregorian = payload["date_gregorian"].isna()
    if missing_gregorian.any():
        payload.loc[missing_gregorian, "date_gregorian"] = payload.loc[
            missing_gregorian, "date_jalali"
        ].map(jalali_to_gregorian_str)

    # One closing per symbol per day (jalali, then gregorian when present).
    payload = payload.drop_duplicates(
        subset=["market_id", "date_jalali"], keep="last"
    )
    has_gregorian = payload["date_gregorian"].notna() & (
        payload["date_gregorian"].astype(str).str.len() > 0
    )
    if has_gregorian.any():
        with_g = payload.loc[has_gregorian].drop_duplicates(
            subset=["market_id", "date_gregorian"], keep="last"
        )
        payload = pd.concat([payload.loc[~has_gregorian], with_g], ignore_index=True)

    payload["source"] = source
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    records = []
    for _, row in payload.iterrows():
        gregorian = row["date_gregorian"]
        records.append(
            (
                row["market_id"],
                row["date_jalali"],
                None if pd.isna(gregorian) else str(gregorian),
                float(row["closing"]),
                row["source"],
                row["updated_at"],
            )
        )

    sql = """
        INSERT INTO market_data
            (market_id, date_jalali, date_gregorian, closing, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(market_id, date_jalali) DO UPDATE SET
            date_gregorian = COALESCE(excluded.date_gregorian, market_data.date_gregorian),
            closing = excluded.closing,
            source = COALESCE(excluded.source, market_data.source),
            updated_at = excluded.updated_at
    """

    owns_connection = conn is None
    if owns_connection:
        with connect() as owned:
            ensure_schema(owned)
            owned.executemany(sql, records)
            return len(records)

    ensure_schema(conn)
    conn.executemany(sql, records)
    return len(records)


def load_market_frame(
    *,
    market_ids: Iterable[str] | None = None,
    config: AppConfig | None = None,
    migrate: bool = True,
) -> pd.DataFrame:
    """Load prices from SQLite as a tidy DataFrame."""
    cfg = config or get_config()
    known = set(cfg.market_by_id())

    with connect(cfg.db_path) as conn:
        if migrate:
            ensure_schema(conn)

        columns = _table_columns(conn)
        if "market_id" in columns:
            query = (
                "SELECT market_id, date_jalali, date_gregorian, closing, source, updated_at "
                "FROM market_data"
            )
            params: list[str] = []
            if market_ids is not None:
                ids = [normalize_market_id(m) for m in market_ids]
                placeholders = ",".join("?" for _ in ids)
                query += f" WHERE market_id IN ({placeholders})"
                params.extend(ids)
            query += " ORDER BY market_id, date_jalali"
            df = pd.read_sql_query(query, conn, params=params or None)
        else:
            # Pre-migration fallback
            query = "SELECT market_type AS market_id, jalali_date AS date_jalali, closing FROM market_data"
            df = pd.read_sql_query(query, conn)
            df["market_id"] = df["market_id"].map(normalize_market_id)
            df["date_gregorian"] = None
            df["source"] = None
            df["updated_at"] = None

    if df.empty:
        return df

    unknown = sorted(set(df["market_id"]) - known)
    if unknown:
        logger.warning("Unknown market_id values in DB (not in config): %s", unknown)

    if market_ids is None:
        enabled = {m.id for m in cfg.enabled_markets()}
        df = df[df["market_id"].isin(enabled)]

    df["closing"] = pd.to_numeric(df["closing"], errors="coerce")
    df = df.dropna(subset=["closing"]).reset_index(drop=True)
    return df


EVENT_CSV_COLUMNS = ("Date", "Event", "tags")
KNOWN_EVENT_TAGS = (
    "conflict",
    "sanctions",
    "protest",
    "us_president",
    "iran_president",
    "iran_faction",
)


def normalize_event_date(value: object) -> str | None:
    """Normalize event date to `YYYY/MM` or `YYYY/MM/DD` Jalali."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace("-", "/")
    if not text or text.lower() in {"none", "nan", "-"}:
        return None
    parts = text.split("/")
    try:
        if len(parts) == 2:
            year, month = int(parts[0]), int(parts[1])
            if not (1 <= month <= 12):
                return None
            return f"{year:04d}/{month:02d}"
        if len(parts) >= 3:
            return normalize_jalali_str(text)
    except (TypeError, ValueError):
        return None
    return None


def load_events(config: AppConfig | None = None) -> pd.DataFrame:
    """Load events.csv and normalize optional tags."""
    cfg = config or get_config()
    path = cfg.events_path
    if not path.exists():
        return pd.DataFrame(columns=["date_jalali", "event", "tags"])

    raw = pd.read_csv(path)
    rename = {}
    if "Date" in raw.columns:
        rename["Date"] = "date_jalali"
    if "Event" in raw.columns:
        rename["Event"] = "event"
    events = raw.rename(columns=rename)
    if "tags" not in events.columns:
        events["tags"] = events["event"].map(_infer_event_tags)
    else:
        events["tags"] = events["tags"].fillna("").astype(str)
    return events[["date_jalali", "event", "tags"]]


def append_event(
    date_jalali: str,
    event: str,
    tags: str | Iterable[str] | None = None,
    *,
    config: AppConfig | None = None,
) -> dict[str, str]:
    """
    Append one event to events.csv. Returns the stored row fields.

    Date may be `YYYY/MM` or `YYYY/MM/DD`. Empty tags are inferred from text.
    """
    cfg = config or get_config()
    date_norm = normalize_event_date(date_jalali)
    if date_norm is None:
        raise ValueError("تاریخ رویداد نامعتبر است (فرمت: YYYY/MM یا YYYY/MM/DD)")

    text = str(event).strip()
    if not text:
        raise ValueError("متن رویداد خالی است")

    if tags is None:
        tag_text = ""
    elif isinstance(tags, str):
        tag_text = tags.strip()
    else:
        tag_text = ",".join(str(t).strip() for t in tags if str(t).strip())

    if not tag_text:
        tag_text = _infer_event_tags(text)

    path = cfg.events_path
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(EVENT_CSV_COLUMNS)
        writer.writerow([date_norm, text, tag_text])

    return {"date_jalali": date_norm, "event": text, "tags": tag_text}


def _infer_event_tags(text: str) -> str:
    """Lightweight tag seeding from event text (no invented political dataset)."""
    tags: list[str] = []
    if not isinstance(text, str):
        return ""
    lowered = text
    if any(k in lowered for k in ("ترامپ", "بایدن", "رئیس‌جمهور آمریکا", "رییس جمهور آمریکا")):
        tags.append("us_president")
    if any(k in lowered for k in ("روحانی", "رئیسی", "پزشکیان", "ریاست جمهوری ایران")):
        tags.append("iran_president")
    if any(k in lowered for k in ("اصلاح", "اصول")):
        tags.append("iran_faction")
    if any(k in lowered for k in ("برجام", "تحریم")):
        tags.append("sanctions")
    if any(k in lowered for k in ("اعتراض", "خیزش")):
        tags.append("protest")
    if any(k in lowered for k in ("اسرائیل", "حماس", "حزب الله")):
        tags.append("conflict")
    return ",".join(tags)
