"""CLI entry: refresh market_data.db from configured sources."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field

import pandas as pd
import requests

from market_trend.config import AppConfig, get_config, resolve_fa_name
from market_trend.db import (
    REPLACE_MARKET_SOURCES,
    backfill_gregorian_dates,
    cleanup_market_data,
    connect,
    delete_market_prices,
    ensure_schema,
    upsert_prices,
)
from market_trend.etl.fetchers import fetch_market

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class MarketFetchResult:
    market_id: str
    status: str  # ok | empty | failed
    rows: int = 0
    min_date: str | None = None
    max_date: str | None = None
    error: str | None = None


@dataclass
class UpdateReport:
    db_path: str
    requested: int = 0
    upserted_rows: int = 0
    elapsed_seconds: float = 0.0
    results: list[MarketFetchResult] = field(default_factory=list)
    db_totals: dict[str, dict] = field(default_factory=dict)

    @property
    def ok(self) -> list[MarketFetchResult]:
        return [r for r in self.results if r.status == "ok"]

    @property
    def empty(self) -> list[MarketFetchResult]:
        return [r for r in self.results if r.status == "empty"]

    @property
    def failed(self) -> list[MarketFetchResult]:
        return [r for r in self.results if r.status == "failed"]


def _db_market_stats(conn) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT market_id,
               COUNT(*) AS row_count,
               MIN(date_jalali) AS min_date,
               MAX(date_jalali) AS max_date
        FROM market_data
        GROUP BY market_id
        ORDER BY market_id
        """
    ).fetchall()
    return {
        row[0]: {
            "row_count": int(row[1]),
            "min_date": row[2],
            "max_date": row[3],
        }
        for row in rows
    }


def print_report(report: UpdateReport, config: AppConfig | None = None) -> None:
    cfg = config or get_config()
    width = 72
    line = "=" * width
    thin = "-" * width

    print()
    print(line)
    print("ETL UPDATE REPORT")
    print(line)
    print(f"Database : {report.db_path}")
    print(f"Duration : {report.elapsed_seconds:.1f}s")
    print(
        f"Summary  : {len(report.ok)} ok | "
        f"{len(report.empty)} empty | "
        f"{len(report.failed)} failed | "
        f"{report.requested} requested"
    )
    print(f"Upserted : {report.upserted_rows:,} rows")
    print(thin)

    header = f"{'Market':<18} {'Status':<8} {'Fetched':>8}  {'Date range':<25}  Name"
    print(header)
    print(thin)

    for result in report.results:
        fa_name = resolve_fa_name(result.market_id, cfg)
        date_range = "—"
        if result.min_date and result.max_date:
            date_range = f"{result.min_date} → {result.max_date}"
        elif result.error:
            date_range = result.error[:25]

        print(
            f"{result.market_id:<18} {result.status:<8} {result.rows:>8,}  "
            f"{date_range:<25}  {fa_name}"
        )

    if report.failed:
        print(thin)
        print("Failures:")
        for result in report.failed:
            print(f"  • {result.market_id}: {result.error}")

    if report.db_totals:
        print(thin)
        print("Database after update (per market):")
        print(f"{'Market':<18} {'Rows':>10}  {'Coverage':<25}  Name")
        print(thin)
        total_rows = 0
        for market_id, stats in report.db_totals.items():
            total_rows += stats["row_count"]
            coverage = f"{stats['min_date']} → {stats['max_date']}"
            fa_name = resolve_fa_name(market_id, cfg)
            print(
                f"{market_id:<18} {stats['row_count']:>10,}  "
                f"{coverage:<25}  {fa_name}"
            )
        print(thin)
        print(f"{'TOTAL':<18} {total_rows:>10,}  markets: {len(report.db_totals)}")

    print(line)
    print()


def update_all(
    *,
    market_ids: list[str] | None = None,
    retries: int = 3,
    sleep_seconds: float = 1.0,
    print_summary: bool = True,
) -> UpdateReport:
    cfg = get_config()
    markets = cfg.enabled_markets()
    if market_ids:
        wanted = set(market_ids)
        markets = tuple(m for m in markets if m.id in wanted)

    started = time.perf_counter()
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    replace_ids: set[str] = set()
    results: list[MarketFetchResult] = []

    for market in markets:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                frame = fetch_market(market, session=session)
                if frame.empty:
                    logger.warning("No rows returned for %s", market.id)
                    results.append(
                        MarketFetchResult(market_id=market.id, status="empty", rows=0)
                    )
                else:
                    frames.append(frame)
                    if market.source in REPLACE_MARKET_SOURCES:
                        replace_ids.add(market.id)
                    results.append(
                        MarketFetchResult(
                            market_id=market.id,
                            status="ok",
                            rows=len(frame),
                            min_date=str(frame["date_jalali"].min()),
                            max_date=str(frame["date_jalali"].max()),
                        )
                    )
                    logger.info("%s: %s rows", market.id, len(frame))
                break
            except Exception as exc:  # noqa: BLE001 - surface per-market failures
                last_error = exc
                logger.warning(
                    "Attempt %s/%s failed for %s: %s",
                    attempt,
                    retries,
                    market.id,
                    exc,
                )
                time.sleep(sleep_seconds * attempt)
        else:
            results.append(
                MarketFetchResult(
                    market_id=market.id,
                    status="failed",
                    error=str(last_error),
                )
            )

    upserted = 0
    db_totals: dict[str, dict] = {}
    with connect(cfg.db_path) as conn:
        ensure_schema(conn)
        for market_id in sorted(replace_ids):
            deleted = delete_market_prices(market_id, conn=conn)
            logger.info("Replaced %s history (%s old rows removed)", market_id, deleted)
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            upserted = upsert_prices(combined, source="etl", conn=conn)
            logger.info("Upserted %s rows into %s", upserted, cfg.db_path)
        else:
            logger.error("No data fetched")
        filled = backfill_gregorian_dates(conn=conn)
        if filled:
            logger.info("Backfilled date_gregorian on %s rows", filled)
        db_totals = _db_market_stats(conn)

    report = UpdateReport(
        db_path=str(cfg.db_path),
        requested=len(markets),
        upserted_rows=upserted,
        elapsed_seconds=time.perf_counter() - started,
        results=results,
        db_totals=db_totals,
    )

    if print_summary:
        print_report(report, cfg)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh market_data.db")
    parser.add_argument(
        "--market",
        action="append",
        dest="markets",
        help="Limit to market id (repeatable)",
    )
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Skip the end-of-run report (log only)",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Normalize/dedupe existing DB rows (no fetch)",
    )
    args = parser.parse_args(argv)

    if args.cleanup_only:
        try:
            stats = cleanup_market_data()
        except Exception:
            logger.exception("Cleanup failed")
            return 1
        print(
            f"Cleanup done: before={stats['before']:,} after={stats['after']:,} "
            f"removed={stats['removed']:,} normalized={stats['normalized']:,}"
        )
        return 0

    try:
        report = update_all(
            market_ids=args.markets,
            retries=args.retries,
            print_summary=not args.quiet,
        )
    except Exception:
        logger.exception("Update failed")
        return 1

    return 1 if report.failed and not report.ok else 0


if __name__ == "__main__":
    sys.exit(main())
