"""Persist and restore dashboard filter presets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from market_trend.time_scopes import TIME_SCOPE_IDS

_PENDING_KEY = "_pending_filter_preset"
# URL query key for the selected bookmark name (custom CCv2 select has no bind=).
FILTER_PRESET_QUERY_KEY = "filter_preset"
_NAME_RE = re.compile(r"[\w\s\-_.\u0600-\u06FF]+", re.UNICODE)


def default_presets_path(root: Path) -> Path:
    return root / "filter_presets.json"


def load_presets(path: Path) -> dict[str, dict[str, Any]]:
    """Load named filter presets from disk. Missing/invalid file → empty."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    presets = raw.get("presets", raw)
    if not isinstance(presets, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, payload in presets.items():
        if isinstance(name, str) and isinstance(payload, dict):
            out[name] = payload
    return out


def save_presets(path: Path, presets: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "presets": presets}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_preset_name(name: str) -> str:
    text = " ".join(str(name).split()).strip()
    if not text:
        raise ValueError("نام فیلتر خالی است.")
    if len(text) > 64:
        raise ValueError("نام فیلتر حداکثر ۶۴ کاراکتر باشد.")
    if _NAME_RE.fullmatch(text) is None:
        raise ValueError("نام فیلتر فقط حروف، عدد، فاصله و - _ . را می‌پذیرد.")
    return text


def upsert_preset(path: Path, name: str, filters: dict[str, Any]) -> str:
    clean = normalize_preset_name(name)
    presets = load_presets(path)
    presets[clean] = dict(filters)
    save_presets(path, presets)
    return clean


def delete_preset(path: Path, name: str) -> bool:
    presets = load_presets(path)
    if name not in presets:
        return False
    del presets[name]
    save_presets(path, presets)
    return True


def coerce_on_off(value: Any, *, default: bool = True) -> bool:
    """Accept bool, on/off, or true/false from widgets / presets / query params."""
    if value in (True, "on", "true", "True", 1, "1"):
        return True
    if value in (False, "off", "false", "False", 0, "0"):
        return False
    return default


def capture_filters(state: dict[str, Any]) -> dict[str, Any]:
    """Snapshot current filter widget values from session-like mapping."""
    markets = state.get("markets", [])
    if not isinstance(markets, list):
        markets = list(markets) if markets else []
    calendar = state.get("calendar", "jalali")
    if calendar not in ("jalali", "gregorian"):
        calendar = "jalali"
    aggregation = state.get("aggregation", "daily")
    if aggregation not in ("daily", "monthly"):
        aggregation = "daily"
    time_scope = state.get("time_scope", "custom")
    if time_scope not in TIME_SCOPE_IDS:
        time_scope = "custom"
    return {
        "normalize_fx": coerce_on_off(state.get("normalize_fx", True)),
        "markets": [str(mid) for mid in markets],
        "calendar": calendar,
        "time_scope": time_scope,
        "start_year": int(state.get("start_year", 0) or 0),
        "start_month": int(state.get("start_month", 1) or 1),
        "end_year": int(state.get("end_year", 0) or 0),
        "end_month": int(state.get("end_month", 12) or 12),
        "aggregation": aggregation,
        "show_events": coerce_on_off(state.get("show_events", True)),
    }


def queue_filter_preset(state: dict[str, Any], preset: dict[str, Any]) -> None:
    state[_PENDING_KEY] = dict(preset)


def apply_pending_filter_preset(
    state: dict[str, Any],
    *,
    df: pd.DataFrame,
    known_market_ids: set[str],
) -> str | None:
    """Apply a queued preset onto widget keys before widgets render.

    Returns the applied preset marker (always None for name; clears pending).
    """
    preset = state.pop(_PENDING_KEY, None)
    if not isinstance(preset, dict):
        return None

    calendar = preset.get("calendar", "jalali")
    if calendar not in ("jalali", "gregorian"):
        calendar = "jalali"
    state["calendar"] = calendar

    year_col = f"{calendar}_year"
    if year_col not in df.columns or df.empty:
        min_year, max_year = 1, 9999
    else:
        min_year = int(df[year_col].min())
        max_year = int(df[year_col].max())

    def _clamp_year(value: Any, default: int) -> int:
        try:
            year = int(value)
        except (TypeError, ValueError):
            year = default
        return max(min_year, min(max_year, year))

    def _clamp_month(value: Any, default: int) -> int:
        try:
            month = int(value)
        except (TypeError, ValueError):
            month = default
        return max(1, min(12, month))

    markets = [
        str(mid)
        for mid in preset.get("markets", [])
        if str(mid) in known_market_ids
    ]
    aggregation = preset.get("aggregation", "daily")
    if aggregation not in ("daily", "monthly"):
        aggregation = "daily"
    time_scope = preset.get("time_scope", "custom")
    if time_scope not in TIME_SCOPE_IDS:
        time_scope = "custom"

    default_start = max(min_year, max_year - 2)
    # Widgets store on/off; presets may still have bool from older saves.
    state["normalize_fx"] = (
        "on" if coerce_on_off(preset.get("normalize_fx", True)) else "off"
    )
    state["markets"] = markets
    state["time_scope"] = time_scope
    # One-run filter override if the selectbox UI is briefly stale after restore.
    state["_preset_force_time_scope"] = time_scope
    state["start_year"] = _clamp_year(preset.get("start_year"), default_start)
    state["start_month"] = _clamp_month(preset.get("start_month"), 1)
    state["end_year"] = _clamp_year(preset.get("end_year"), max_year)
    state["end_month"] = _clamp_month(preset.get("end_month"), 12)
    state["aggregation"] = aggregation
    state["show_events"] = (
        "on" if coerce_on_off(preset.get("show_events", True)) else "off"
    )
    return "applied"
