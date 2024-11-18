"""Relative time-scope presets for dashboard date filtering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from persiantools.jdatetime import JalaliDate

CalendarName = Literal["jalali", "gregorian"]
TimeScopeId = str

# (id, Persian label)
TIME_SCOPE_OPTIONS: tuple[tuple[TimeScopeId, str], ...] = (
    ("custom", "سفارشی"),
    ("this_week", "هفته جاری"),
    ("last_week", "هفته گذشته"),
    ("last_7_days", "۷ روز اخیر"),
    ("last_14_days", "۱۴ روز اخیر"),
    ("last_30_days", "۳۰ روز اخیر"),
    ("this_month", "ماه جاری"),
    ("last_month", "ماه گذشته"),
    ("last_3_months", "۳ ماه اخیر"),
    ("last_6_months", "۶ ماه اخیر"),
    ("this_season", "فصل جاری"),
    ("last_season", "فصل گذشته"),
    ("this_year", "سال جاری"),
    ("last_year", "سال گذشته"),
    ("all", "کل بازه"),
)

TIME_SCOPE_IDS: frozenset[str] = frozenset(scope_id for scope_id, _ in TIME_SCOPE_OPTIONS)
TIME_SCOPE_LABELS: dict[str, str] = dict(TIME_SCOPE_OPTIONS)


@dataclass(frozen=True)
class DateRange:
    """Inclusive gregorian date bounds (and jalali string forms)."""

    start: date
    end: date

    @property
    def start_jalali(self) -> str:
        return _jalali_str(JalaliDate(self.start))

    @property
    def end_jalali(self) -> str:
        return _jalali_str(JalaliDate(self.end))

    @property
    def start_year_month(self) -> tuple[int, int]:
        return self.start.year, self.start.month

    @property
    def end_year_month(self) -> tuple[int, int]:
        return self.end.year, self.end.month

    def jalali_year_month_bounds(self) -> tuple[tuple[int, int], tuple[int, int]]:
        start_j = JalaliDate(self.start)
        end_j = JalaliDate(self.end)
        return (start_j.year, start_j.month), (end_j.year, end_j.month)


def _jalali_str(value: JalaliDate) -> str:
    return f"{value.year:04d}/{value.month:02d}/{value.day:02d}"


def _clamp(range_: DateRange, *, data_min: date | None, data_max: date | None) -> DateRange:
    start, end = range_.start, range_.end
    if data_min is not None and start < data_min:
        start = data_min
    if data_max is not None and end > data_max:
        end = data_max
    if start > end:
        start = end
    return DateRange(start=start, end=end)


def _week_start(day: date, *, calendar: CalendarName) -> date:
    """Saturday start for jalali; Monday start for gregorian (ISO)."""
    wd = day.weekday()  # Mon=0 .. Sun=6
    if calendar == "jalali":
        # Saturday = 5
        return day - timedelta(days=(wd - 5) % 7)
    return day - timedelta(days=wd)


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _shift_months(day: date, months: int) -> date:
    """Shift calendar month; clamp day into target month length."""
    year = day.year
    month = day.month + months
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    # last day of target month
    if month == 12:
        last = 31
    else:
        last = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


def _season_start(day: date) -> date:
    """Gregorian meteorological-style quarters: JFM, AMJ, JAS, OND."""
    month = ((day.month - 1) // 3) * 3 + 1
    return date(day.year, month, 1)


def _jalali_month_start(day: date) -> date:
    j = JalaliDate(day)
    return JalaliDate(j.year, j.month, 1).to_gregorian()


def _jalali_shift_months(day: date, months: int) -> date:
    j = JalaliDate(day)
    year, month = j.year, j.month + months
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    # clamp day
    if month == 12:
        last = JalaliDate(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = JalaliDate(year, month + 1, 1) - timedelta(days=1)
    day_n = min(j.day, last.day)
    return JalaliDate(year, month, day_n).to_gregorian()


def _jalali_season_start(day: date) -> date:
    j = JalaliDate(day)
    month = ((j.month - 1) // 3) * 3 + 1
    return JalaliDate(j.year, month, 1).to_gregorian()


def _jalali_year_start(day: date) -> date:
    j = JalaliDate(day)
    return JalaliDate(j.year, 1, 1).to_gregorian()


def _jalali_full_year_bounds(year: int) -> tuple[date, date]:
    start = JalaliDate(year, 1, 1).to_gregorian()
    end = (JalaliDate(year + 1, 1, 1) - timedelta(days=1)).to_gregorian()
    return start, end


def resolve_time_scope(
    scope_id: TimeScopeId,
    *,
    calendar: CalendarName = "jalali",
    today: date | None = None,
    data_min: date | None = None,
    data_max: date | None = None,
) -> DateRange | None:
    """
    Resolve a relative scope to an inclusive gregorian date range.

    Returns None for ``custom`` (caller keeps manual year/month widgets).
    """
    if scope_id not in TIME_SCOPE_IDS:
        scope_id = "custom"
    if scope_id == "custom":
        return None

    today = today or date.today()
    if data_max is not None and today > data_max:
        # Prefer "as of latest data" when wall-clock is ahead of DB.
        today = data_max

    if scope_id == "all":
        if data_min is None or data_max is None:
            return DateRange(start=today, end=today)
        return DateRange(start=data_min, end=data_max)

    if calendar == "jalali":
        range_ = _resolve_jalali(scope_id, today=today)
    else:
        range_ = _resolve_gregorian(scope_id, today=today)

    return _clamp(range_, data_min=data_min, data_max=data_max)


def _resolve_gregorian(scope_id: str, *, today: date) -> DateRange:
    if scope_id == "this_week":
        start = _week_start(today, calendar="gregorian")
        return DateRange(start=start, end=today)
    if scope_id == "last_week":
        this_start = _week_start(today, calendar="gregorian")
        end = this_start - timedelta(days=1)
        start = end - timedelta(days=6)
        return DateRange(start=start, end=end)
    if scope_id == "last_7_days":
        return DateRange(start=today - timedelta(days=6), end=today)
    if scope_id == "last_14_days":
        return DateRange(start=today - timedelta(days=13), end=today)
    if scope_id == "last_30_days":
        return DateRange(start=today - timedelta(days=29), end=today)
    if scope_id == "this_month":
        return DateRange(start=_month_start(today), end=today)
    if scope_id == "last_month":
        prev = _month_start(today) - timedelta(days=1)
        return DateRange(start=_month_start(prev), end=prev)
    if scope_id == "last_3_months":
        return DateRange(start=_shift_months(today, -3), end=today)
    if scope_id == "last_6_months":
        return DateRange(start=_shift_months(today, -6), end=today)
    if scope_id == "this_season":
        return DateRange(start=_season_start(today), end=today)
    if scope_id == "last_season":
        this_start = _season_start(today)
        end = this_start - timedelta(days=1)
        start = _season_start(end)
        return DateRange(start=start, end=end)
    if scope_id == "this_year":
        return DateRange(start=date(today.year, 1, 1), end=today)
    if scope_id == "last_year":
        return DateRange(
            start=date(today.year - 1, 1, 1),
            end=date(today.year - 1, 12, 31),
        )
    return DateRange(start=today, end=today)


def _resolve_jalali(scope_id: str, *, today: date) -> DateRange:
    if scope_id == "this_week":
        start = _week_start(today, calendar="jalali")
        return DateRange(start=start, end=today)
    if scope_id == "last_week":
        this_start = _week_start(today, calendar="jalali")
        end = this_start - timedelta(days=1)
        start = end - timedelta(days=6)
        return DateRange(start=start, end=end)
    if scope_id == "last_7_days":
        return DateRange(start=today - timedelta(days=6), end=today)
    if scope_id == "last_14_days":
        return DateRange(start=today - timedelta(days=13), end=today)
    if scope_id == "last_30_days":
        return DateRange(start=today - timedelta(days=29), end=today)
    if scope_id == "this_month":
        return DateRange(start=_jalali_month_start(today), end=today)
    if scope_id == "last_month":
        prev = _jalali_month_start(today) - timedelta(days=1)
        return DateRange(start=_jalali_month_start(prev), end=prev)
    if scope_id == "last_3_months":
        return DateRange(start=_jalali_shift_months(today, -3), end=today)
    if scope_id == "last_6_months":
        return DateRange(start=_jalali_shift_months(today, -6), end=today)
    if scope_id == "this_season":
        return DateRange(start=_jalali_season_start(today), end=today)
    if scope_id == "last_season":
        this_start = _jalali_season_start(today)
        end = this_start - timedelta(days=1)
        start = _jalali_season_start(end)
        return DateRange(start=start, end=end)
    if scope_id == "this_year":
        return DateRange(start=_jalali_year_start(today), end=today)
    if scope_id == "last_year":
        j = JalaliDate(today)
        start, end = _jalali_full_year_bounds(j.year - 1)
        return DateRange(start=start, end=end)
    return DateRange(start=today, end=today)


def format_range_label(range_: DateRange, *, calendar: CalendarName) -> str:
    if calendar == "jalali":
        return f"{range_.start_jalali} تا {range_.end_jalali}"
    return f"{range_.start.isoformat()} تا {range_.end.isoformat()}"
