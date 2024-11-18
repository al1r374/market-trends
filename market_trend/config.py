"""Load and expose project configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config.yaml"

JALALI_SEASONS = ("بهار", "تابستان", "پاییز", "زمستان")
GREGORIAN_SEASONS = ("spring", "summer", "autumn", "winter")

JALALI_MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)

GREGORIAN_MONTHS = (
    "ژانویه",
    "فوریه",
    "مارس",
    "آوریل",
    "مه",
    "ژوئن",
    "ژوئیه",
    "اوت",
    "سپتامبر",
    "اکتبر",
    "نوامبر",
    "دسامبر",
)

GREGORIAN_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def month_name(month: int | str, calendar: str = "jalali") -> str:
    """Return display name for month number 1..12."""
    index = int(month) - 1
    if index < 0 or index > 11:
        raise ValueError(f"Invalid month: {month}")
    if calendar == "gregorian":
        return GREGORIAN_MONTHS[index]
    return JALALI_MONTHS[index]


def month_options(calendar: str = "jalali") -> dict[str, int]:
    """Map display label -> month number for UI selectboxes."""
    names = GREGORIAN_MONTHS if calendar == "gregorian" else JALALI_MONTHS
    return {f"{i:02d} — {name}": i for i, name in enumerate(names, start=1)}


def months_for_calendar(calendar: str = "jalali") -> tuple[str, ...]:
    return GREGORIAN_MONTHS if calendar == "gregorian" else JALALI_MONTHS

# Legacy notebook used "Doje"; DB and config use "Doge".
MARKET_ID_ALIASES = {"Doje": "Doge"}


@dataclass(frozen=True)
class MarketConfig:
    id: str
    fa_name: str
    color: str
    category: str
    enabled: bool
    source: str
    url: str
    currency: str  # "irr" | "usd" — quote currency of stored closing prices


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    events_path: Path
    presets_path: Path
    start_jalali: str
    end_jalali: str
    chart_height: int
    chart_template: str
    markets: tuple[MarketConfig, ...]

    def market_by_id(self) -> dict[str, MarketConfig]:
        return {m.id: m for m in self.markets}

    def enabled_markets(self) -> tuple[MarketConfig, ...]:
        return tuple(m for m in self.markets if m.enabled)

    def fa_names(self) -> dict[str, str]:
        return {m.id: m.fa_name for m in self.markets}

    def colors(self) -> dict[str, str]:
        return {m.fa_name: m.color for m in self.markets}

    def colors_by_id(self) -> dict[str, str]:
        return {m.id: m.color for m in self.markets}

    def currency_by_id(self) -> dict[str, str]:
        return {m.id: m.currency for m in self.markets}


def _infer_currency(raw: dict[str, Any]) -> str:
    explicit = raw.get("currency")
    if explicit in {"irr", "usd"}:
        return str(explicit)
    if raw.get("category") == "crypto" or raw.get("source") == "binance_klines":
        return "usd"
    return "irr"


def _parse_market(raw: dict[str, Any]) -> MarketConfig:
    return MarketConfig(
        id=str(raw["id"]),
        fa_name=str(raw["fa_name"]),
        color=str(raw.get("color", "#888888")),
        category=str(raw.get("category", "other")),
        enabled=bool(raw.get("enabled", True)),
        source=str(raw.get("source", "")),
        url=str(raw.get("url", "")),
        currency=_infer_currency(raw),
    )


def load_config(path: Path | str | None = None) -> AppConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    paths = raw.get("paths", {})
    date_range = raw.get("date_range", {})
    chart = raw.get("chart", {})
    markets = tuple(_parse_market(item) for item in raw.get("markets", []))

    db_path = Path(paths.get("db", "market_data.db"))
    events_path = Path(paths.get("events", "events.csv"))
    presets_path = Path(paths.get("presets", "filter_presets.json"))
    if not db_path.is_absolute():
        db_path = ROOT_DIR / db_path
    if not events_path.is_absolute():
        events_path = ROOT_DIR / events_path
    if not presets_path.is_absolute():
        presets_path = ROOT_DIR / presets_path

    return AppConfig(
        db_path=db_path,
        events_path=events_path,
        presets_path=presets_path,
        start_jalali=str(date_range.get("start_jalali", "1395/01/01")),
        end_jalali=str(date_range.get("end_jalali", "1410/01/01")),
        chart_height=int(chart.get("height", 600)),
        chart_template=str(chart.get("template", "plotly_white")),
        markets=markets,
    )


@lru_cache(maxsize=8)
def _cached_config(path: str, mtime_ns: int) -> AppConfig:
    return load_config(path)


def get_config(path: Path | str | None = None) -> AppConfig:
    """Load config, refreshing when the YAML file changes on disk."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    try:
        mtime_ns = config_path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return _cached_config(str(config_path.resolve()), mtime_ns)


def normalize_market_id(market_id: str) -> str:
    return MARKET_ID_ALIASES.get(market_id, market_id)


def resolve_fa_name(market_id: str, config: AppConfig | None = None) -> str:
    cfg = config or get_config()
    normalized = normalize_market_id(market_id)
    market = cfg.market_by_id().get(normalized)
    return market.fa_name if market else normalized
