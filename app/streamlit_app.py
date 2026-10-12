"""Streamlit dashboard for Iranian market trend analysis."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_trend import charts, metrics
from market_trend.config import JALALI_MONTHS, get_config, month_name
from market_trend.db import (
    KNOWN_EVENT_TAGS,
    append_event,
    load_events,
    load_market_frame,
)
from market_trend.enrich import (
    add_calendar_features,
    aggregate_prices,
    fill_daily_gaps,
    filter_markets,
)
from market_trend.components.filter_preset_select import filter_preset_select
from market_trend.components.menu_actions import mount_menu_actions
from market_trend.etl.update import update_all
from market_trend.presets import (
    FILTER_PRESET_QUERY_KEY,
    apply_pending_filter_preset,
    capture_filters,
    coerce_on_off,
    delete_preset,
    load_presets,
    queue_filter_preset,
    upsert_preset,
)
from market_trend.time_scopes import (
    TIME_SCOPE_LABELS,
    TIME_SCOPE_OPTIONS,
    format_range_label,
    resolve_time_scope,
)

st.set_page_config(
    page_title="بازارها | Market Trend",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_CSS = """
<style>
    @font-face {
        font-family: "IRANSans-Edit";
        src: url("/app/static/fonts/IRANSans-Edit.ttf") format("truetype");
        font-weight: normal;
        font-style: normal;
        font-display: swap;
    }

    /* App text only — do not target span/div (breaks Material icon fonts) */
    html, body, .stApp,
    .stMarkdown, .stText, .stCaption,
    .stSelectbox, .stMultiSelect, .stRadio, .stCheckbox,
    .stButton, .stMetric, .stNumberInput, .stTextInput,
    [data-testid="stSidebar"],
    [data-testid="stWidgetLabel"],
    [data-testid="stMarkdownContainer"],
    [data-testid="stTextInputField"],
    h1, h2, h3, h4, h5, h6, p, label {
        font-family: "IRANSans-Edit", Tahoma, sans-serif !important;
    }

    /* Hide "Press Enter to apply / submit" widget hints. */
    [data-testid="InputInstructions"] {
        display: none !important;
    }

    /* Restore Streamlit / Material icon fonts */
    .material-symbols-rounded,
    .material-symbols-outlined,
    .material-symbols-sharp,
    .material-icons,
    [class*="material-symbols"],
    span[data-testid="stIconMaterial"],
    [data-testid="stIconMaterial"],
    [data-testid="stExpanderToggleIcon"],
    [data-testid="stSidebarCollapseButton"] span,
    [data-testid="baseButton-headerNoPadding"] span,
    button[kind] span[class*="material"],
    i.material-icons {
        font-family: "Material Symbols Rounded" !important;
        font-variation-settings: "FILL" 0, "wght" 400, "GRAD" 0, "opsz" 24;
    }

    /* Keep document LTR (no dir/direction: rtl). Align UI text right. */
    html, body,
    [data-testid="stAppViewContainer"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stSidebar"],
    [data-testid="stSidebarContent"],
    .stApp,
    .main,
    .block-container {
        direction: ltr !important;
    }

    html, body, .stApp, .main, .block-container,
    [data-testid="stAppViewContainer"],
    [data-testid="stHeader"],
    [data-testid="stSidebar"],
    [data-testid="stSidebarContent"],
    [data-testid="stMarkdownContainer"],
    [data-testid="stWidgetLabel"],
    [data-testid="stMetric"],
    [data-testid="stMetricLabel"],
    [data-testid="stMetricValue"],
    [data-testid="stMetricDelta"],
    [data-testid="stCaptionContainer"],
    [data-testid="stAlert"],
    [data-testid="stTabs"],
    [data-testid="stExpander"],
    .stMarkdown, .stText, .stCaption, .stTitle, .stHeader, .stSubheader,
    .stSelectbox, .stMultiSelect, .stRadio, .stCheckbox, .stButton,
    .stMetric, .stNumberInput, .stTextInput, .stDateInput,
    h1, h2, h3, h4, h5, h6, p, label, li {
        text-align: right !important;
    }

    /* Table headers + cells centered (incl. nested spans) */
    [data-testid="stTable"] table th,
    [data-testid="stTable"] table th *,
    [data-testid="stTable"] table td,
    [data-testid="stTable"] table td *,
    .stTable table th,
    .stTable table th *,
    .stTable table td,
    .stTable table td * {
        text-align: center !important;
        vertical-align: middle !important;
    }

    /* Tabs on the right; روند first from the right. No dir/direction: rtl. */
    [data-testid="stTabs"] [data-baseweb="tab-list"],
    [data-testid="stTabs"] [role="tablist"] {
        display: flex !important;
        flex-direction: row-reverse !important;
        justify-content: flex-start !important;
        width: 100% !important;
    }

    /* Equal-height cards in horizontal metric rows */
    [data-testid="stHorizontalBlock"] > [data-testid="stElementContainer"],
    [data-testid="stHorizontalBlock"] > .stElementContainer {
        height: 100%;
        align-self: stretch;
    }
    [data-testid="stHorizontalBlock"] [data-testid="stMetric"] {
        height: 100%;
    }

    .st-emotion-cache-10p9htt {
        margin-bottom: 0 !important;
    }

    /* Header: filter list + bookmark + title vertically centered. */
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save),
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        [data-testid="stColumn"],
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        [data-testid="stVerticalBlock"],
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        [data-testid="stLayoutWrapper"],
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        [data-testid="stElementContainer"] {
        overflow: unset !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save) {
        align-items: center !important;
        gap: 0.5rem !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        > [data-testid="stLayoutWrapper"],
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        > [data-testid="stElementContainer"] {
        display: flex !important;
        align-items: center !important;
        align-self: center !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        [data-testid="stHeadingWithActionElements"],
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save) h1 {
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1.25 !important;
    }
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save)
        [data-testid="stHeadingWithActionElements"] {
        display: flex !important;
        align-items: center !important;
        direction: rtl !important;
    }
    /* Swap title text and heading-link icon order. */
    div[data-testid="stHorizontalBlock"]:has(.st-key-filter_preset_save) h1 {
        display: flex !important;
        flex-direction: row-reverse !important;
        align-items: center !important;
        gap: 0.35rem !important;
    }

    /* Bookmark save button: force vertical center in the header row. */
    .st-key-filter_preset_save {
        display: flex !important;
        align-items: center !important;
        align-self: center !important;
        height: auto !important;
        margin-top: 0 !important;
        margin-bottom: 0 !important;
    }
    .st-key-filter_preset_save [data-testid="stButton"],
    .st-key-filter_preset_save .stButton {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 !important;
        height: 100% !important;
    }
    .st-key-filter_preset_save [data-testid="stTooltipIcon"],
    .st-key-filter_preset_save [data-testid="stTooltipHoverTarget"] {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: auto !important;
        height: 100% !important;
    }
    .st-key-filter_preset_save button {
        margin: 0 !important;
        align-self: center !important;
    }

    /* Custom main-menu action items. */
    [data-testid="stMainMenuItem-reload-data"],
    [data-testid="stMainMenuItem-reload-data"] [data-testid="stMainMenuItemLabel"],
    [data-testid="stMainMenuItem-run-etl"],
    [data-testid="stMainMenuItem-run-etl"] [data-testid="stMainMenuItemLabel"],
    [data-testid="stMainMenuItem-data-sources"],
    [data-testid="stMainMenuItem-data-sources"] [data-testid="stMainMenuItemLabel"] {
        font-family: "IRANSans-Edit", Tahoma, sans-serif !important;
    }

    /* Invisible menu-action bridge (no layout). */
    .st-key-mt_menu_actions,
    .st-key-mt_menu_actions_v8,
    div[data-testid="stElementContainer"].st-key-mt_menu_actions,
    div[data-testid="stElementContainer"].st-key-mt_menu_actions_v8 {
        display: none !important;
    }

    /* Filter field labels sit on the right; help icon left of the title. */
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"],
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stMultiSelect label,
    [data-testid="stSidebar"] .stSegmentedControl label,
    [data-testid="stPopoverBody"] [data-testid="stWidgetLabel"] {
        display: flex !important;
        flex-direction: row-reverse !important;
        justify-content: flex-start !important;
        align-items: center !important;
        gap: 0.35rem !important;
        width: 100% !important;
        text-align: right !important;
    }
    [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    [data-testid="stPopoverBody"] [data-testid="stWidgetLabel"] p {
        text-align: right !important;
        margin: 0 !important;
    }

    /* Modal dialogs (e.g. ذخیره فیلتر): IRANSans + RTL; close on the left. */
    [role="dialog"],
    [role="dialog"] *,
    [role="dialog"] h2,
    [role="dialog"] p,
    [role="dialog"] label,
    [role="dialog"] button,
    [role="dialog"] input,
    [role="dialog"] [data-testid="stMarkdownContainer"],
    [role="dialog"] [data-testid="stWidgetLabel"],
    [role="dialog"] [data-testid="stTextInputField"],
    [role="dialog"] [data-testid="stTextInputRootElement"],
    [role="dialog"] [data-testid="stTextInputRootElement"] input,
    [role="dialog"] .stTextInput,
    [role="dialog"] .stButton,
    .st-key-save_filter_dialog_name,
    .st-key-save_filter_dialog_name input,
    .st-key-save_filter_dialog_submit,
    .st-key-save_filter_dialog_submit button {
        font-family: "IRANSans-Edit", Tahoma, sans-serif !important;
    }
    [role="dialog"] {
        direction: rtl !important;
        text-align: right !important;
    }
    [role="dialog"] h2,
    [role="dialog"] [data-testid="stMarkdownContainer"],
    [role="dialog"] [data-testid="stWidgetLabel"],
    [role="dialog"] .stTextInput,
    [role="dialog"] .stButton,
    [role="dialog"] p,
    [role="dialog"] label {
        text-align: right !important;
        direction: rtl !important;
    }
    [role="dialog"] [data-testid="stWidgetLabel"] {
        display: flex !important;
        flex-direction: row-reverse !important;
        justify-content: flex-end !important;
        align-items: center !important;
        gap: 0.35rem !important;
        width: 100% !important;
    }
    [role="dialog"] [data-testid="stTextInputField"],
    [role="dialog"] [data-testid="stTextInputRootElement"] input {
        direction: rtl !important;
        text-align: right !important;
    }
    [role="dialog"] > button[aria-label="Close"] {
        right: auto !important;
        left: 0.75rem !important;
    }
    /* Dialog title: drop LTR spacing that leaves a gap beside the close button. */
    [role="dialog"] h2 > span,
    .st-emotion-cache-1mf1b6k {
        margin-right: 0 !important;
    }

</style>
"""
st.markdown(APP_CSS, unsafe_allow_html=True)

# Streamlit has no API for actionable main-menu items; inject into the popover
# and dispatch events handled by an invisible CCv2 bridge (no URL / no buttons).
st.html(
    """
<script>
(function () {
  if (window.__mtMainMenuActionsV8Installed) return;
  window.__mtMainMenuActionsV8Installed = true;

  var ITEMS = [
    {
      testid: "stMainMenuItem-events",
      label: "Events",
      key: "events",
    },
    {
      testid: "stMainMenuItem-data-sources",
      label: "Data sources",
      key: "data_sources",
    },
    {
      testid: "stMainMenuItem-run-etl",
      label: "Update from sources",
      key: "run_etl",
    },
    {
      testid: "stMainMenuItem-reload-data",
      label: "Reload data",
      key: "reload_data",
    },
  ];

  function triggerAction(key) {
    window.dispatchEvent(
      new CustomEvent("mt-menu-action", { detail: key })
    );
  }

  function makeItem(printBtn, item) {
    // Build a plain button (do not clone React-managed menu nodes).
    var btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("role", "menuitem");
    btn.tabIndex = -1;
    btn.setAttribute("data-testid", item.testid);
    if (printBtn && printBtn.className) btn.className = printBtn.className;

    var label = document.createElement("span");
    label.setAttribute("data-testid", "stMainMenuItemLabel");
    label.textContent = item.label;
    var printLabel = printBtn
      ? printBtn.querySelector('[data-testid="stMainMenuItemLabel"]')
      : null;
    if (printLabel && printLabel.className) label.className = printLabel.className;
    btn.appendChild(label);

    btn.addEventListener(
      "click",
      function (event) {
        event.preventDefault();
        event.stopPropagation();
        triggerAction(item.key);
      },
      true
    );
    return btn;
  }

  var injecting = false;

  function inject() {
    var list = document.querySelector('[data-testid="stMainMenuList"]');
    if (!list || injecting) return;

    injecting = true;
    try {
      var printBtn = list.querySelector('[data-testid="stMainMenuItem-print"]');
      var anchor = printBtn || null;
      for (var i = 0; i < ITEMS.length; i++) {
        var item = ITEMS[i];
        if (list.querySelector('[data-testid="' + item.testid + '"]')) continue;
        var btn = makeItem(printBtn, item);
        if (anchor) anchor.before(btn);
        else list.appendChild(btn);
      }
    } finally {
      injecting = false;
    }
  }

  var obs = new MutationObserver(function () {
    inject();
  });
  obs.observe(document.documentElement, { childList: true, subtree: true });
  inject();
})();
</script>
""",
    unsafe_allow_javascript=True,
)


def _file_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


@st.cache_data(show_spinner="در حال بارگذاری داده…")
def load_enriched(_db_mtime_ns: int, _config_mtime_ns: int) -> pd.DataFrame:
    cfg = get_config()
    raw = load_market_frame(config=cfg)
    return add_calendar_features(raw, config=cfg)


@st.cache_data
def load_events_cached(_events_mtime_ns: int) -> pd.DataFrame:
    return load_events()


def market_label(market) -> str:
    """Sidebar label: Persian name + English id for search."""
    return f"{market.fa_name} ({market.id})"


PRICE_COLUMNS = frozenset({"closing", "value", "start_price", "end_price", "قیمت پایانی"})

SOURCE_LABELS = {
    "tsetmc": "TSETMC",
    "tgju_index": "TGJU (شاخص)",
    "tgju_stock": "TGJU (سهام)",
    "tgju_indicator": "TGJU (شاخص قیمت)",
    "binance_klines": "Binance",
    "abantether_line_chart": "Abantether",
    "coinlore_hdata": "CoinLore",
}

CATEGORY_LABELS = {
    "fund": "صندوق",
    "equity": "سهام",
    "gold": "طلا",
    "fx": "ارز",
    "crypto": "رمزارز",
    "commodity": "کالا",
    "other": "سایر",
}


def sources_dataframe(markets) -> pd.DataFrame:
    """Build a table of data-gathering resources for each market symbol."""
    rows = [
        {
            "نماد": market.id,
            "نام": market.fa_name,
            "دسته": CATEGORY_LABELS.get(market.category, market.category),
            "منبع": SOURCE_LABELS.get(market.source, market.source or "—"),
            "کد منبع": market.source or "—",
            "آدرس": market.url or "",
            "ارز": "ریال" if market.currency == "irr" else "دلار",
            "فعال": "بله" if market.enabled else "خیر",
        }
        for market in markets
    ]
    return pd.DataFrame(rows)


def centered_column_config(df: pd.DataFrame) -> dict:
    """Center-align columns; thousand-separate known price fields."""
    config: dict = {}
    for col in df.columns:
        name = str(col)
        if name in PRICE_COLUMNS:
            config[name] = st.column_config.NumberColumn(
                alignment="center",
                format="%,d",
            )
        else:
            config[name] = st.column_config.Column(alignment="center")
    if df.index.name is not None:
        config[str(df.index.name)] = st.column_config.Column(alignment="center")
    return config


def show_centered_table(
    df: pd.DataFrame,
    *,
    hide_index: bool = False,
    height: int | None = None,
) -> None:
    """Sortable dataframe with centered cell content."""
    kwargs: dict = {
        "column_config": centered_column_config(df),
        "width": "stretch",
        "hide_index": hide_index,
    }
    if height is not None:
        kwargs["height"] = height
    st.dataframe(df, **kwargs)


def _set_active_filter_preset(name: str | None) -> None:
    """Keep session + URL in sync so the bookmark label survives refresh."""
    if name:
        st.session_state["active_filter_preset"] = name
        st.query_params[FILTER_PRESET_QUERY_KEY] = name
        return
    st.session_state.pop("active_filter_preset", None)
    if FILTER_PRESET_QUERY_KEY in st.query_params:
        del st.query_params[FILTER_PRESET_QUERY_KEY]


def _render_app_view_header(title: str, *, back_key: str) -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button(
            "بازگشت",
            icon=":material/arrow_forward:",
            key=back_key,
            type="tertiary",
        ):
            st.session_state["app_view"] = "dashboard"
            st.rerun()
        st.subheader(title)


def render_sources_page(cfg, selected_ids: list[str]) -> None:
    """Full-page data-sources view (opened from the main menu)."""
    _render_app_view_header("منابع داده", back_key="sources_back")
    st.caption(
        "آدرس و نوع منبع هر نماد طبق `config.yaml` — "
        "همین منابع برای به‌روزرسانی دیتابیس استفاده می‌شوند."
    )
    only_selected = st.toggle(
        "فقط بازارهای انتخاب‌شده",
        value=False,
        key="sources_only_selected",
    )
    source_markets = (
        tuple(m for m in cfg.markets if m.id in selected_ids)
        if only_selected
        else cfg.markets
    )
    sources_df = sources_dataframe(source_markets)
    if sources_df.empty:
        st.info("نمادی برای نمایش منبع نیست.")
        return
    link_config = centered_column_config(sources_df)
    link_config["آدرس"] = st.column_config.LinkColumn(
        "آدرس",
        display_text="باز کردن",
        alignment="center",
    )
    st.dataframe(
        sources_df,
        column_config=link_config,
        width="stretch",
        hide_index=True,
        height=min(52 + 35 * len(sources_df), 720),
    )
    by_source = (
        sources_df.groupby("منبع", sort=False)
        .size()
        .reset_index(name="تعداد")
        .sort_values("تعداد", ascending=False)
    )
    st.caption(
        f"{len(sources_df):,} نماد — "
        + " · ".join(
            f"{row['منبع']}: {int(row['تعداد'])}" for _, row in by_source.iterrows()
        )
    )


def render_events_page(cfg, df: pd.DataFrame, events: pd.DataFrame) -> None:
    """Full-page events view (opened from the main menu)."""
    _render_app_view_header("رویدادها", back_key="events_back")
    st.subheader("افزودن رویداد")
    st.caption(
        "تاریخ شمسی به‌صورت سال/ماه ذخیره می‌شود و روی نمودار روند نمایش داده می‌شود."
    )
    if df.empty or "jalali_year" not in df.columns:
        st.warning("داده‌ای برای تعیین بازه سال نیست.")
        return
    min_j_year = int(df["jalali_year"].min())
    max_j_year = int(df["jalali_year"].max())
    with st.form("add_event_form", clear_on_submit=True, border=True):
        year_col, month_col_ui = st.columns(2)
        event_year = year_col.number_input(
            "سال شمسی",
            min_value=min_j_year - 5,
            max_value=max_j_year + 5,
            value=max_j_year,
            step=1,
        )
        month_labels = [
            f"{i:02d} — {name}" for i, name in enumerate(JALALI_MONTHS, start=1)
        ]
        event_month_label = month_col_ui.selectbox(
            "ماه شمسی",
            options=month_labels,
            index=0,
        )
        event_text = st.text_area(
            "شرح رویداد",
            placeholder="مثلاً: توافق جدید هسته‌ای",
            height=100,
        )
        event_tags = st.multiselect(
            "برچسب‌ها (اختیاری)",
            options=list(KNOWN_EVENT_TAGS),
            help="اگر خالی بماند، از روی متن رویداد حدس زده می‌شود.",
        )
        submitted = st.form_submit_button(
            "ذخیره رویداد",
            type="primary",
            icon=":material/event:",
        )

    if submitted:
        month_num = int(event_month_label.split("—", 1)[0].strip())
        try:
            saved = append_event(
                f"{int(event_year):04d}/{month_num:02d}",
                event_text,
                event_tags,
                config=cfg,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(
                f"رویداد ذخیره شد: {saved['date_jalali']} — {saved['event']}"
            )
            st.rerun()

    st.subheader("فهرست رویدادها")
    events_sorted = events.sort_values("date_jalali", ascending=False)
    events_table = events_sorted.rename(
        columns={
            "date_jalali": "تاریخ",
            "event": "رویداد",
            "tags": "برچسب",
        }
    )
    show_centered_table(events_table, hide_index=True, height=480)
    st.caption(
        f"{len(events):,} رویداد در `{cfg.events_path.name}` — "
        "برچسب خالی از متن رویداد استخراج می‌شود."
    )


@st.dialog("ذخیره فیلتر", width="small")
def save_filter_dialog(presets_path: Path) -> None:
    """Ask for a bookmark name, then save the current filter snapshot."""
    name = st.text_input(
        "نام فیلتر",
        placeholder="مثلاً: کریپتو و طلا",
        key="save_filter_dialog_name",
    )
    if st.button("ذخیره", type="primary", width="stretch", key="save_filter_dialog_submit"):
        try:
            snapshot = capture_filters(st.session_state)
            saved_name = upsert_preset(presets_path, name, snapshot)
        except ValueError as exc:
            st.error(str(exc))
        else:
            _set_active_filter_preset(saved_name)
            st.rerun()


def jalali_options(df: pd.DataFrame) -> list:
    if df.empty:
        return []
    return sorted(df["jalali_date"].unique())


def main() -> None:
    # Drop legacy query-param triggers so old menu links don't stick in the URL.
    for _qp in ("reload_data", "run_etl"):
        if _qp in st.query_params:
            del st.query_params[_qp]

    def _reload_data() -> None:
        st.cache_data.clear()
        st.rerun()

    def _run_etl() -> None:
        with st.spinner("در حال دریافت و به‌روزرسانی داده از منابع…"):
            try:
                report = update_all(print_summary=False)
                st.session_state["etl_flash"] = {
                    "ok": bool(report.ok) or not report.failed,
                    "upserted": report.upserted_rows,
                    "ok_n": len(report.ok),
                    "failed_n": len(report.failed),
                    "empty_n": len(report.empty),
                    "elapsed": report.elapsed_seconds,
                    "failed_ids": [r.market_id for r in report.failed],
                }
            except Exception as exc:  # noqa: BLE001 - show in UI
                st.session_state["etl_flash"] = {
                    "ok": False,
                    "error": str(exc),
                }
        st.cache_data.clear()
        st.rerun()

    def _open_events() -> None:
        st.session_state["app_view"] = "events"

    def _open_data_sources() -> None:
        st.session_state["app_view"] = "sources"

    mount_menu_actions(
        on_reload_data=_reload_data,
        on_run_etl=_run_etl,
        on_events=_open_events,
        on_data_sources=_open_data_sources,
    )

    cfg = get_config()
    df = load_enriched(
        _file_mtime_ns(cfg.db_path),
        _file_mtime_ns(ROOT / "config.yaml"),
    )
    events = load_events_cached(_file_mtime_ns(cfg.events_path))

    etl_flash = st.session_state.pop("etl_flash", None)
    if isinstance(etl_flash, dict):
        if etl_flash.get("error"):
            st.error(f"به‌روزرسانی از منابع ناموفق بود: {etl_flash['error']}")
        elif etl_flash.get("ok"):
            failed_n = int(etl_flash.get("failed_n") or 0)
            msg = (
                f"به‌روزرسانی انجام شد: {etl_flash.get('ok_n', 0)} موفق، "
                f"{etl_flash.get('upserted', 0)} ردیف، "
                f"{etl_flash.get('elapsed', 0):.1f}ثانیه"
            )
            if failed_n:
                failed_ids = ", ".join(etl_flash.get("failed_ids") or [])
                st.warning(f"{msg} — ناموفق: {failed_n}" + (f" ({failed_ids})" if failed_ids else ""))
            else:
                st.success(msg)
        else:
            st.error("به‌روزرسانی از منابع ناموفق بود.")

    if df.empty:
        st.error("داده‌ای در دیتابیس نیست. ابتدا `python -m market_trend.etl.update` را اجرا کنید.")
        return

    markets = cfg.enabled_markets()
    label_by_id = {m.id: market_label(m) for m in markets}
    id_by_fa = {m.fa_name: m.id for m in markets}
    colors = cfg.colors()

    known_market_ids = set(label_by_id)
    saved_presets = load_presets(cfg.presets_path)
    preset_names = sorted(saved_presets)
    presets_path = cfg.presets_path

    # Restore selected bookmark from URL after refresh (session state is empty).
    if "active_filter_preset" not in st.session_state:
        qp_preset = st.query_params.get(FILTER_PRESET_QUERY_KEY)
        if qp_preset in saved_presets:
            st.session_state["active_filter_preset"] = qp_preset
            queue_filter_preset(st.session_state, saved_presets[qp_preset])
        elif qp_preset is not None:
            del st.query_params[FILTER_PRESET_QUERY_KEY]

    apply_pending_filter_preset(
        st.session_state,
        df=df,
        known_market_ids=known_market_ids,
    )

    def _apply_bookmark(name: str) -> None:
        presets = load_presets(presets_path)
        preset = presets.get(name)
        if preset is None:
            return
        # Apply in the callback (before widgets) so time_scope/years win over
        # any stale bind/URL values from the previous relative scope.
        queue_filter_preset(st.session_state, preset)
        apply_pending_filter_preset(
            st.session_state,
            df=df,
            known_market_ids=known_market_ids,
        )
        _set_active_filter_preset(name)

    def _delete_bookmark(name: str) -> None:
        delete_preset(presets_path, name)
        if st.session_state.get("active_filter_preset") == name:
            _set_active_filter_preset(None)

    active_preset = st.session_state.get("active_filter_preset")
    if active_preset not in preset_names:
        if active_preset is not None:
            _set_active_filter_preset(None)
        active_preset = None
    elif st.query_params.get(FILTER_PRESET_QUERY_KEY) != active_preset:
        st.query_params[FILTER_PRESET_QUERY_KEY] = active_preset

    # Controls on the left, title on the right (LTR columns → title is last).
    controls_col, title_col = st.columns(
        [1.6, 2.2],
        vertical_alignment="center",
        gap="small",
        wrap=False,
    )
    with controls_col:
        with st.container(
            horizontal=True,
            wrap=False,
            vertical_alignment="center",
            gap="small",
        ):
            filter_preset_select(
                preset_names,
                value=active_preset,
                placeholder="انتخاب فیلتر",
                key="filter_preset_select",
                on_select=_apply_bookmark,
                on_delete=_delete_bookmark,
                width=280,
            )
            if st.button(
                ":material/bookmark:",
                key="filter_preset_save",
                help="ذخیره فیلتر فعلی",
            ):
                save_filter_dialog(cfg.presets_path)
    with title_col:
        with st.container(horizontal=True, horizontal_alignment="right"):
            st.title("تحلیل روند بازارها")

    with st.sidebar:
        st.header("فیلترها")
        default_ids = [
            m
            for m in (
                "BourseBox",
                "PAXG",
                "ProBox",
                "HomeBox",
                "SilverBox",
                "Synergy",
                "Bitcoin",
                "COPXON",
                "Dollar",
            )
            if m in label_by_id
        ]
        market_ids = [m.id for m in markets]
        selected_ids = st.multiselect(
            "بازارها",
            options=market_ids,
            default=default_ids,
            format_func=lambda mid: label_by_id[mid],
            key="markets",
            bind="query-params",
        )
        selected_ids = [mid for mid in selected_ids if mid in label_by_id]
        selected_fa = [cfg.fa_names()[mid] for mid in selected_ids]

        calendar = st.session_state.get("calendar", "jalali")
        if calendar not in ("jalali", "gregorian"):
            calendar = "jalali"

        calendar = st.segmented_control(
            "تقویم",
            options=["jalali", "gregorian"],
            default=calendar,
            format_func=lambda x: "شمسی" if x == "jalali" else "میلادی",
            key="calendar",
            bind="query-params",
            required=True,
            width="stretch",
        ) or calendar

        year_col = f"{calendar}_year"
        month_col = f"{calendar}_month"
        year_month_col = f"{calendar}_year_month"
        min_year = int(df[year_col].min())
        max_year = int(df[year_col].max())
        default_start_year = max(min_year, max_year - 2)
        default_end_month = int(
            df.loc[df[year_col] == max_year, month_col].astype(int).max()
        )
        year_options = list(range(min_year, max_year + 1))
        month_numbers = list(range(1, 13))

        # No bind on time_scope: restoring a bookmark scope must not fight a
        # leftover ?time_scope=… relative value in the URL.
        scope_ids = [scope_id for scope_id, _ in TIME_SCOPE_OPTIONS]
        st.session_state.setdefault("time_scope", "last_30_days")
        forced_scope = st.session_state.pop("_preset_force_time_scope", None)
        time_scope = st.selectbox(
            "بازه زمانی",
            options=scope_ids,
            format_func=lambda sid: TIME_SCOPE_LABELS[sid],
            key="time_scope",
        )
        if forced_scope in TIME_SCOPE_LABELS:
            # Do not write session state here — widget already instantiated.
            time_scope = forced_scope
        elif time_scope not in TIME_SCOPE_LABELS:
            time_scope = "custom"

        g_dates = pd.to_datetime(df["gregorian_date"], errors="coerce")
        data_min = g_dates.min()
        data_max = g_dates.max()
        data_min_d = data_min.date() if pd.notna(data_min) else None
        data_max_d = data_max.date() if pd.notna(data_max) else None
        resolved_range = resolve_time_scope(
            time_scope,
            calendar=calendar,  # type: ignore[arg-type]
            data_min=data_min_d,
            data_max=data_max_d,
        )

        custom_range = resolved_range is None
        if resolved_range is not None:
            st.caption(
                format_range_label(resolved_range, calendar=calendar)  # type: ignore[arg-type]
            )
            if calendar == "jalali":
                (sy, sm), (ey, em) = resolved_range.jalali_year_month_bounds()
            else:
                sy, sm = resolved_range.start_year_month
                ey, em = resolved_range.end_year_month
            # Mirror resolved bounds into disabled year/month widgets for display.
            st.session_state["start_year"] = int(sy)
            st.session_state["start_month"] = int(sm)
            st.session_state["end_year"] = int(ey)
            st.session_state["end_month"] = int(em)
        else:
            # Custom range: seed defaults once (no index= — conflicts with preset writes).
            st.session_state.setdefault("start_year", default_start_year)
            st.session_state.setdefault("start_month", 1)
            st.session_state.setdefault("end_year", max_year)
            st.session_state.setdefault("end_month", default_end_month)
            # Clamp if calendar switch left an out-of-range year.
            if st.session_state["start_year"] not in year_options:
                st.session_state["start_year"] = default_start_year
            if st.session_state["end_year"] not in year_options:
                st.session_state["end_year"] = max_year

        start_year_col, start_month_col = st.columns(2)
        with start_year_col:
            start_year = st.selectbox(
                "از سال",
                options=year_options,
                key="start_year",
                bind="query-params",
                disabled=not custom_range,
            )
        with start_month_col:
            start_month = st.selectbox(
                "از ماه",
                options=month_numbers,
                format_func=lambda num: month_name(num, calendar),
                key="start_month",
                bind="query-params",
                disabled=not custom_range,
            )
        end_year_col, end_month_col = st.columns(2)
        with end_year_col:
            end_year = st.selectbox(
                "تا سال",
                options=year_options,
                key="end_year",
                bind="query-params",
                disabled=not custom_range,
            )
        with end_month_col:
            end_month = st.selectbox(
                "تا ماه",
                options=month_numbers,
                format_func=lambda num: month_name(num, calendar),
                key="end_month",
                bind="query-params",
                disabled=not custom_range,
            )

        aggregation = st.session_state.get("aggregation", "daily")
        if aggregation not in ("daily", "monthly"):
            aggregation = "daily"
        aggregation = st.segmented_control(
            "تجمیع",
            options=["daily", "monthly"],
            default=aggregation,
            format_func=lambda x: "روزانه" if x == "daily" else "ماهانه",
            key="aggregation",
            bind="query-params",
            required=True,
            width="stretch",
        ) or aggregation
        normalize_default = (
            "on" if coerce_on_off(st.session_state.get("normalize_fx", "on")) else "off"
        )
        normalize_choice = st.segmented_control(
            "نرمال‌سازی ارزی",
            options=["on", "off"],
            default=normalize_default,
            format_func=lambda x: "فعال" if x == "on" else "خاموش",
            key="normalize_fx",
            bind="query-params",
            required=True,
            width="stretch",
            help=(
                "رمزارزها به دلار/تتر هستند؛ صندوق‌ها و طلای داخلی به ریال. "
                "با حالت فعال، قیمت‌های دلاری در نرخ تتر ضرب می‌شوند و "
                "روی همه نمودارها اعمال می‌شود."
            ),
        ) or normalize_default
        normalize_fx = normalize_choice == "on"
        events_default = (
            "on" if coerce_on_off(st.session_state.get("show_events", "on")) else "off"
        )
        events_choice = st.segmented_control(
            "نمایش رویدادها روی نمودار",
            options=["on", "off"],
            default=events_default,
            format_func=lambda x: "فعال" if x == "on" else "خاموش",
            key="show_events",
            bind="query-params",
            required=True,
            width="stretch",
        ) or events_default
        show_events = events_choice == "on"

    app_view = st.session_state.get("app_view") or "dashboard"
    if app_view == "events":
        render_events_page(cfg, df, events)
        return
    if app_view == "sources":
        render_sources_page(cfg, selected_ids)
        return

    if not selected_ids:
        st.warning("حداقل یک بازار انتخاب کنید.")
        return

    filtered = filter_markets(df, selected_ids)
    if resolved_range is not None:
        row_dates = pd.to_datetime(filtered["gregorian_date"], errors="coerce").dt.date
        filtered = filtered[
            (row_dates >= resolved_range.start) & (row_dates <= resolved_range.end)
        ]
    else:
        start_ym = f"{int(start_year):04d}-{int(start_month):02d}"
        end_ym = f"{int(end_year):04d}-{int(end_month):02d}"
        filtered = filtered[
            (filtered[year_month_col] >= start_ym) & (filtered[year_month_col] <= end_ym)
        ]

    if filtered.empty:
        st.warning("برای این فیلتر داده‌ای نیست.")
        return

    # Real observations only for coverage; gap-filled series for table + charts.
    filled = fill_daily_gaps(filtered, config=cfg)

    fx_market_id = "USDT"
    fx_all = df[df["market_id"] == fx_market_id]
    numeraire = "irr" if normalize_fx else "native"
    priced = filled.copy()
    if normalize_fx:
        try:
            fx_by_date = metrics.build_fx_by_date(fx_all, dates=filled["date_jalali"])
            priced = metrics.prices_in_numeraire(
                filled,
                numeraire="irr",
                fx_by_date=fx_by_date,
                currency_by_id=cfg.currency_by_id(),
                fx_market_id=fx_market_id,
            )
        except ValueError as exc:
            st.warning(str(exc))
            priced = filled.copy()
            priced["value"] = pd.to_numeric(priced["closing"], errors="coerce")
            normalize_fx = False
            numeraire = "native"
    else:
        priced["value"] = pd.to_numeric(priced["closing"], errors="coerce")

    # Single analysis frame for all charts: normalized closing when toggle is on.
    analysis = priced.dropna(subset=["value"]).copy()
    analysis["closing"] = analysis["value"]
    if analysis.empty:
        st.warning("پس از نرمال‌سازی ارزی داده‌ای برای نمایش نیست.")
        return

    agg = aggregate_prices(analysis, calendar=calendar, aggregation=aggregation)
    date_col = "date"

    events_view = events.copy()

    calendar_label = "شمسی" if calendar == "jalali" else "میلادی"
    (
        tab_overview,
        tab_corr,
        tab_growth,
        tab_season,
        tab_risk,
        tab_data,
    ) = st.tabs(
        [
            "روند",
            "همبستگی",
            "رشد و رتبه",
            "فصلی/ماهانه",
            "ریسک",
            "داده‌ها",
        ]
    )

    with tab_overview:
        st.subheader("مقایسه رشد در بازه انتخابی")
        period_growth = pd.DataFrame()
        try:
            # Do not align to peer coverage: the sidebar time scope already
            # defines the window. Aligning would make GoldBox's % change when
            # USOON vs Zar is co-selected (different overlapping days).
            period_growth = metrics.selected_period_growth(
                filtered,
                numeraire=numeraire,
                fx_df=fx_all if normalize_fx else None,
                currency_by_id=cfg.currency_by_id(),
                fx_market_id=fx_market_id,
                align_period=False,
            )
        except ValueError as exc:
            st.warning(str(exc))

        if period_growth.empty:
            st.info("برای محاسبه رشد، هر بازار باید حداقل دو مشاهده در بازه داشته باشد.")
        else:
            best = period_growth.iloc[0]
            worst = period_growth.iloc[-1]
            with st.container(horizontal=True):
                st.metric(
                    "بهترین رشد",
                    f"{best['market_name_fa']}",
                    f"{best['growth_pct']:+.1f}%",
                    border=True,
                    height="stretch",
                )
                st.metric(
                    "ضعیف‌ترین رشد",
                    f"{worst['market_name_fa']}",
                    f"{worst['growth_pct']:+.1f}%",
                    border=True,
                    height="stretch",
                )
            chart_title = (
                "رشد درصد در بازه انتخابی — نرمال‌سازی ارزی"
                if normalize_fx
                else "رشد درصد در بازه انتخابی"
            )
            st.plotly_chart(
                charts.horizontal_metric_bars(
                    period_growth,
                    metric="growth_pct",
                    title=chart_title,
                    config=cfg,
                    diverging=True,
                ),
                width="stretch",
            )

        st.subheader("روند رشد")
        exclude_ids = [fx_market_id] if normalize_fx else None
        growth_series = metrics.indexed_growth_series(
            agg,
            date_col=date_col,
            exclude_market_ids=exclude_ids,
        )
        if growth_series.empty:
            st.info("برای رسم روند رشد، هر بازار باید حداقل دو مشاهده هم‌پوشان داشته باشد.")
        else:
            growth_title = (
                "مقایسه رشد — نرمال‌سازی ارزی"
                if normalize_fx
                else "مقایسه رشد"
            )
            st.plotly_chart(
                charts.growth_trend(
                    growth_series,
                    date_col=date_col,
                    color_map=colors,
                    calendar=calendar,
                    title=growth_title,
                    config=cfg,
                ),
                use_container_width=True,
            )

    with tab_corr:
        st.subheader("ماتریس همبستگی")
        corr_ids = [mid for mid in selected_ids if mid != fx_market_id] if normalize_fx else selected_ids
        corr = metrics.correlation_matrix(analysis, corr_ids, value_col="closing")
        title = "همبستگی (نرمال‌سازی ارزی)" if normalize_fx else "همبستگی بازارها"
        st.plotly_chart(
            charts.correlation_heatmap(corr, title=title, config=cfg),
            use_container_width=True,
        )
        corr_table = corr.round(2)
        if corr_table.index.name is None:
            corr_table = corr_table.rename_axis("بازار")
        show_centered_table(corr_table)

    with tab_growth:
        st.subheader("رشد سالانه (Top 5)")
        top = metrics.top_n_yearly(analysis, n=5, calendar=calendar)
        year_col = f"{calendar}_year"
        if not top.empty:
            st.plotly_chart(
                charts.stacked_growth_bars(top, x_col=year_col, title="۵ بازار برتر هر سال", config=cfg),
                use_container_width=True,
            )

        st.subheader("رتبه‌بندی سالانه")
        ranks = metrics.yearly_ranks(analysis, calendar=calendar)
        if not ranks.empty:
            st.plotly_chart(
                charts.rank_heatmap(ranks, year_col=year_col, config=cfg),
                use_container_width=True,
            )

        st.subheader("میانگین رتبه (بدون سال جاری ناقص)")
        current_year = int(df[f"{calendar}_year"].max())
        mean_ranks = metrics.mean_yearly_rank(
            analysis, calendar=calendar, exclude_years=[current_year]
        )
        if not mean_ranks.empty:
            st.plotly_chart(
                charts.horizontal_metric_bars(
                    mean_ranks, metric="mean_rank", title="میانگین رتبه (کمتر = بهتر)", config=cfg
                ),
                use_container_width=True,
            )

        st.subheader("مقایسه دوره‌های چندساله")
        width = st.selectbox("طول دوره", options=[2, 3, 4], index=0)
        multi = metrics.multi_year_growth(analysis, width=width, calendar=calendar)
        period_col = f"{calendar}_{width}_year_period"
        if not multi.empty:
            st.plotly_chart(
                charts.stacked_growth_bars(
                    multi, x_col=period_col, title=f"رشد دوره‌های {width} ساله", config=cfg
                ),
                use_container_width=True,
            )

    with tab_season:
        st.subheader("رشد فصلی")
        seasonal = metrics.seasonal_growth(analysis, calendar=calendar)
        if not seasonal.empty:
            season_col = f"{calendar}_season"
            st.plotly_chart(
                charts.stacked_growth_bars(
                    seasonal, x_col=season_col, title="رشد فصلی", config=cfg
                ),
                use_container_width=True,
            )

        focus_fa = st.selectbox("بازار برای جزئیات ماهانه", options=selected_fa)
        focus_id = id_by_fa[focus_fa]
        focus_df = analysis[analysis["market_id"] == focus_id]
        st.plotly_chart(
            charts.monthly_subplots(
                focus_df, market_name=focus_fa, calendar=calendar, config=cfg
            ),
            use_container_width=True,
        )

        st.subheader("جایگاه ماه جاری نسبت به میانگین تاریخی")
        snap = metrics.seasonality_snapshot(analysis, market_id=focus_id, calendar=calendar)
        if not snap.empty:
            display_cols = [
                c
                for c in (
                    "month_name",
                    f"{calendar}_month",
                    "hist_mean_growth",
                    "latest_growth",
                    "delta_vs_hist",
                )
                if c in snap.columns
            ]
            show_centered_table(snap[display_cols], hide_index=True)
            chart_df = snap.rename(columns={"hist_mean_growth": "growth_rate"}).assign(
                market_name_fa="میانگین تاریخی"
            )
            x_col = "month_name" if "month_name" in chart_df.columns else f"{calendar}_month"
            st.plotly_chart(
                charts.stacked_growth_bars(
                    chart_df,
                    x_col=x_col,
                    title=f"میانگین رشد تاریخی ماهانه ({calendar_label})",
                    config=cfg,
                ),
                use_container_width=True,
            )

    with tab_risk:
        st.subheader(
            "خلاصه ریسک و بازدهی",
            help=(
                "برای هر بازار در بازهٔ انتخابی: "
                "**بازدهی کل** از اولین تا آخرین قیمت، "
                "**بازدهی اوج** از شروع تا بالاترین قیمت، "
                "**بدترین سقوط** بیشترین افت نسبت به اوج قبلی، "
                "و **نوسان** انحراف‌معیار بازدهٔ روزانه. "
                "همه به‌صورت درصد (به‌جز نوسان که نسبت روزانه است)."
            ),
        )
        summary = metrics.risk_summary(analysis)
        if not summary.empty:
            summary_table = (
                summary[
                    [
                        "market_name_fa",
                        "total_return_pct",
                        "peak_return_pct",
                        "max_drawdown_pct",
                        "volatility",
                    ]
                ]
                .round(2)
                .rename(
                    columns={
                        "market_name_fa": "بازار",
                        "total_return_pct": "بازدهی کل ٪",
                        "peak_return_pct": "بازدهی اوج ٪",
                        "max_drawdown_pct": "بدترین سقوط ٪",
                        "volatility": "نوسان",
                    }
                )
            )
            show_centered_table(summary_table, hide_index=True)
            cols = st.columns(3)
            with cols[0]:
                st.plotly_chart(
                    charts.horizontal_metric_bars(
                        summary, metric="total_return_pct", title="بازدهی کل ٪", config=cfg
                    ),
                    use_container_width=True,
                )
            with cols[1]:
                st.plotly_chart(
                    charts.horizontal_metric_bars(
                        summary, metric="max_drawdown_pct", title="بدترین سقوط ٪", config=cfg
                    ),
                    use_container_width=True,
                )
            with cols[2]:
                vol = metrics.volatility_ranking(analysis)
                st.plotly_chart(
                    charts.horizontal_metric_bars(
                        vol, metric="volatility", title="نوسان (کمتر = پایدارتر)", config=cfg
                    ),
                    use_container_width=True,
                )

        st.subheader(
            "وقتی لنگرها منفی‌اند، کجا مثبت است؟",
            help=(
                "روزهایی را پیدا می‌کند که همهٔ بازارهای لنگر همزمان بازدهٔ روزانهٔ منفی داشته‌اند؛ "
                "سپس میانگین بازدهٔ همان روزها را برای بقیهٔ بازارها نشان می‌دهد. "
                "عدد مثبت یعنی آن بازار در روزهای نزولی لنگرها، به‌طور متوسط رشد کرده است."
            ),
        )
        anchors_fa = st.multiselect(
            "بازارهای لنگر (مثلاً بورس و طلا)",
            options=selected_fa,
            default=[n for n in selected_fa if n in ("بورس", "طلا")][:2],
        )
        if len(anchors_fa) >= 1:
            anchors = [id_by_fa[n] for n in anchors_fa]
            try:
                conditional = metrics.conditional_up_markets(analysis, anchor_ids=anchors)
                if conditional.empty:
                    st.info("روزی که همه لنگرها همزمان منفی باشند پیدا نشد.")
                else:
                    st.plotly_chart(
                        charts.horizontal_metric_bars(
                            conditional,
                            metric="mean_return_pct",
                            title="میانگین بازده در روزهای منفی لنگر",
                            config=cfg,
                        ),
                        use_container_width=True,
                    )
            except ValueError as exc:
                st.warning(str(exc))

    with tab_data:
        st.subheader("داده‌های ذخیره‌شده")
        real_n = int(filled["is_real"].sum()) if "is_real" in filled.columns else len(filled)
        guessed_n = len(filled) - real_n
        st.caption(
            f"{len(filled):,} ردیف ({real_n:,} واقعی / {guessed_n:,} تخمینی) "
            f"برای بازارها و بازه انتخاب‌شده ({calendar_label})"
        )

        table_cols = [
            "market_id",
            "market_name_fa",
            "date_jalali",
            "date_gregorian",
            "closing",
            "is_real",
        ]
        table_cols = [c for c in table_cols if c in filled.columns]
        table_df = (
            filled[table_cols]
            .sort_values(["market_id", "date_jalali"])
            .reset_index(drop=True)
        )
        if "is_real" in table_df.columns:
            table_df = table_df.rename(columns={"is_real": "وضعیت داده"})
            table_df["وضعیت داده"] = table_df["وضعیت داده"].map(
                {True: "واقعی", False: "تخمینی"}
            )

        show_centered_table(table_df, hide_index=True, height=520)

        csv_bytes = table_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="دانلود CSV",
            data=csv_bytes,
            file_name="market_data_filtered.csv",
            mime="text/csv",
        )

        st.subheader("روند قیمت")
        if show_events:
            fig = charts.price_trend_with_events(
                agg,
                events_view,
                date_col=date_col,
                calendar=calendar,
                color_map=colors,
                config=cfg,
            )
        else:
            fig = charts.price_trend(
                agg,
                date_col=date_col,
                color_map=colors,
                calendar=calendar,
                config=cfg,
            )
        st.plotly_chart(fig, width="stretch")

        st.subheader("پوشش داده")
        heat = metrics.coverage_heatmap(filtered)
        st.plotly_chart(charts.coverage_heatmap(heat, config=cfg), use_container_width=True)

if __name__ == "__main__":
    main()
