"""Market data fetch adapters (tgju / tsetmc / binance / abantether / coinlore)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from persiantools.jdatetime import JalaliDate

from market_trend.config import MarketConfig
from market_trend.db import normalize_jalali_str

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60
USER_AGENT = "market-trend/0.1 (+local research)"
BINANCE_KLINES_LIMIT = 1000
# SHIBUSDT listed on Binance around May 2021; start a bit earlier for safety.
BINANCE_HISTORY_START_MS = int(
    datetime(2021, 5, 1, tzinfo=timezone.utc).timestamp() * 1000
)
TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def clean_value(value: Any) -> Any:
    if value == "-" or value is None or value == "":
        return None
    if not isinstance(value, str):
        return value

    match = re.search(r'<span class="(?:low|high)" dir="ltr">([\d%,]+)<', value)
    if match:
        number = match.group(1).replace(",", "")
        return f"-{number}" if 'class="low"' in value else number

    match = re.search(
        r'([\d.,]+)\s*<span class="currency-type">میلیون</span>', value
    )
    if match:
        number = float(match.group(1).replace(",", ""))
        return int(number * 1_000_000)

    match = re.search(
        r'<span class="label">قیمت:</span><span class="value">([\d.,]+)</span>',
        value,
        re.DOTALL,
    )
    if match:
        return float(match.group(1).replace(",", ""))

    return value.strip()


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_json(url: str, *, session: requests.Session | None = None) -> Any:
    sess = session or _session()
    response = sess.get(url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _to_float_series(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .replace({"": None, "None": None, "nan": None})
        .pipe(pd.to_numeric, errors="coerce")
    )


def _empty_frame(market_id: str) -> pd.DataFrame:
    return pd.DataFrame(columns=["market_id", "date_jalali", "date_gregorian", "closing"])


def _finalize_price_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dates and keep one row per market per day."""
    if df.empty:
        return df.reset_index(drop=True)

    out = df.copy()
    out["date_jalali"] = out["date_jalali"].map(normalize_jalali_str)
    if "date_gregorian" in out.columns:
        out["date_gregorian"] = out["date_gregorian"].map(_normalize_gregorian)
    else:
        out["date_gregorian"] = None
    out["closing"] = pd.to_numeric(out["closing"], errors="coerce")
    out = out.dropna(subset=["market_id", "date_jalali", "closing"])
    out = out.drop_duplicates(subset=["market_id", "date_jalali"], keep="last")
    has_gregorian = out["date_gregorian"].notna()
    if has_gregorian.any():
        with_g = out.loc[has_gregorian].drop_duplicates(
            subset=["market_id", "date_gregorian"], keep="last"
        )
        out = pd.concat([out.loc[~has_gregorian], with_g], ignore_index=True)
    return out[["market_id", "date_jalali", "date_gregorian", "closing"]].reset_index(
        drop=True
    )


def _normalize_gregorian(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace("/", "-")
    if not text or text.lower() in {"none", "nan", "-"}:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _gregorian_and_jalali_from_utc_ms(open_time_ms: int) -> tuple[str, str]:
    gregorian = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc).date()
    jalali = JalaliDate.to_jalali(gregorian.year, gregorian.month, gregorian.day)
    return gregorian.strftime("%Y-%m-%d"), jalali.strftime("%Y/%m/%d")


def _gregorian_and_jalali_from_unix_tehran(unix_seconds: int) -> tuple[str, str]:
    """Map unix seconds to calendar date in Asia/Tehran (Abantether daily points)."""
    gregorian = datetime.fromtimestamp(unix_seconds, tz=TEHRAN_TZ).date()
    jalali = JalaliDate.to_jalali(gregorian.year, gregorian.month, gregorian.day)
    return gregorian.strftime("%Y-%m-%d"), jalali.strftime("%Y/%m/%d")


def _parse_tsetmc(raw: dict, market_id: str) -> pd.DataFrame:
    rows = raw.get("closingPriceDaily", [])
    if not rows:
        return _empty_frame(market_id)
    df = pd.DataFrame(rows)
    gregorian_dates: list[str] = []
    jalali_dates: list[str] = []
    for value in df["dEven"]:
        text = str(value)
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:8])
        gregorian_dates.append(f"{year:04d}-{month:02d}-{day:02d}")
        jalali_dates.append(
            JalaliDate.to_jalali(year, month, day).strftime("%Y/%m/%d")
        )
    df["date_gregorian"] = gregorian_dates
    df["date_jalali"] = jalali_dates
    df["closing"] = pd.to_numeric(df["pClosing"], errors="coerce")
    df["market_id"] = market_id
    return _finalize_price_frame(
        df[["market_id", "date_jalali", "date_gregorian", "closing"]]
    )


def _parse_tgju_table(raw: dict, market_id: str, source: str) -> pd.DataFrame:
    rows = raw.get("data", [])
    if not rows:
        return _empty_frame(market_id)

    cleaned = [[clean_value(item) for item in row] for row in rows]

    if source == "tgju_index":
        columns = ["jalali", "closing", "lowest", "highest"]
    elif source == "tgju_stock":
        columns = ["jalali", "a", "b", "closing", "c"]
    else:
        columns = [
            "opening",
            "lowest",
            "highest",
            "closing",
            "change_amount",
            "change_percentage",
            "gregorian_date",
            "jalali",
        ]

    width = len(cleaned[0])
    df = pd.DataFrame(cleaned, columns=columns[:width])
    if "closing" not in df.columns or "jalali" not in df.columns:
        logger.warning("Unexpected columns for %s: %s", market_id, list(df.columns))
        return _empty_frame(market_id)

    df["closing"] = _to_float_series(df["closing"])
    df = df.rename(columns={"jalali": "date_jalali"})
    if "gregorian_date" in df.columns:
        df["date_gregorian"] = df["gregorian_date"].map(_normalize_gregorian)
    else:
        df["date_gregorian"] = None
    df["market_id"] = market_id
    return _finalize_price_frame(
        df[["market_id", "date_jalali", "date_gregorian", "closing"]]
    )


def _binance_query_params(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    query = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
    if "symbol" not in query:
        raise ValueError(f"binance_klines URL missing symbol: {url}")
    query.setdefault("interval", "1d")
    return query


def fetch_binance_klines(
    url: str, *, session: requests.Session | None = None
) -> list[list[Any]]:
    """Paginate Binance daily klines until exhaustion."""
    sess = session or _session()
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}{urlparse(url).path}"
    params = _binance_query_params(url)
    start_ms = BINANCE_HISTORY_START_MS
    rows: list[list[Any]] = []

    while True:
        request_params = {
            **params,
            "startTime": start_ms,
            "limit": BINANCE_KLINES_LIMIT,
        }
        response = sess.get(base, params=request_params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        rows.extend(batch)
        next_start = int(batch[-1][0]) + 86_400_000
        if next_start <= start_ms or len(batch) < BINANCE_KLINES_LIMIT:
            break
        start_ms = next_start

    return rows


def _parse_binance_klines(raw: list[list[Any]], market_id: str) -> pd.DataFrame:
    if not raw:
        return _empty_frame(market_id)

    records = []
    for candle in raw:
        open_time_ms = int(candle[0])
        date_gregorian, date_jalali = _gregorian_and_jalali_from_utc_ms(open_time_ms)
        records.append(
            {
                "market_id": market_id,
                "date_jalali": date_jalali,
                "date_gregorian": date_gregorian,
                "closing": float(candle[4]),
            }
        )
    df = pd.DataFrame.from_records(records)
    return _finalize_price_frame(df)


def _parse_abantether_line_chart(raw: dict, market_id: str) -> pd.DataFrame:
    """Parse Abantether line_chart points: [unix_seconds, price_str].

    Use interval=yearly in the URL for ~1y of daily closes. interval=daily is
    intraday (e.g. 10m bars) and is collapsed to one closing per Tehran day.
    """
    points = raw.get("points") or []
    if not points:
        return _empty_frame(market_id)

    records = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        date_gregorian, date_jalali = _gregorian_and_jalali_from_unix_tehran(int(point[0]))
        records.append(
            {
                "market_id": market_id,
                "date_jalali": date_jalali,
                "date_gregorian": date_gregorian,
                "closing": float(point[1]),
            }
        )
    if not records:
        return _empty_frame(market_id)
    return _finalize_price_frame(pd.DataFrame.from_records(records))


COINLORE_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://www.coinlore.com",
    "Referer": "https://www.coinlore.com/",
}


def _coinlore_hdata_url(url: str) -> str:
    """Ensure CoinLore hdatav2 URL includes s/e params (empty body without them)."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.setdefault("s", ["undefined"])
    query.setdefault("e", ["undefined"])
    flat = {key: values[0] for key, values in query.items() if values}
    return parsed._replace(query=urlencode(flat)).geturl()


def fetch_coinlore_hdata(
    url: str, *, session: requests.Session | None = None
) -> dict[str, Any]:
    """Fetch CoinLore hdatav2 JSON (requires Origin/Referer and s/e params)."""
    sess = session or _session()
    response = sess.get(
        _coinlore_hdata_url(url),
        headers=COINLORE_HEADERS,
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    if not response.content:
        raise ValueError("CoinLore returned empty body; check URL and Origin/Referer")
    return response.json()


def _parse_coinlore_hdata(raw: dict, market_id: str) -> pd.DataFrame:
    """Parse CoinLore hdatav2 `price` series: [unix_ms, usd_price].

    History is mostly daily; the recent window can be hourly. Collapse to one
    close per UTC calendar day (last point wins).
    """
    points = raw.get("price") or []
    if not points:
        return _empty_frame(market_id)

    records = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        if point[1] is None:
            continue
        date_gregorian, date_jalali = _gregorian_and_jalali_from_utc_ms(int(point[0]))
        records.append(
            {
                "market_id": market_id,
                "date_jalali": date_jalali,
                "date_gregorian": date_gregorian,
                "closing": float(point[1]),
            }
        )
    if not records:
        return _empty_frame(market_id)
    return _finalize_price_frame(pd.DataFrame.from_records(records))


def fetch_market(market: MarketConfig, *, session: requests.Session | None = None) -> pd.DataFrame:
    """Fetch one market and return standardized rows."""
    if not market.url:
        logger.warning("No URL configured for %s", market.id)
        return _empty_frame(market.id)

    sess = session or _session()
    logger.info("Fetching %s via %s", market.id, market.source)

    if market.source == "tsetmc":
        raw = fetch_json(market.url, session=sess)
        return _parse_tsetmc(raw, market.id)
    if market.source in {"tgju_index", "tgju_stock", "tgju_indicator"}:
        raw = fetch_json(market.url, session=sess)
        return _parse_tgju_table(raw, market.id, market.source)
    if market.source == "binance_klines":
        raw = fetch_binance_klines(market.url, session=sess)
        return _parse_binance_klines(raw, market.id)
    if market.source == "abantether_line_chart":
        raw = fetch_json(market.url, session=sess)
        return _parse_abantether_line_chart(raw, market.id)
    if market.source == "coinlore_hdata":
        raw = fetch_coinlore_hdata(market.url, session=sess)
        return _parse_coinlore_hdata(raw, market.id)

    raise ValueError(f"Unsupported source '{market.source}' for market {market.id}")
