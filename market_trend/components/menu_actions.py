"""Invisible bridge: main-menu JS → Streamlit triggers (no visible widgets)."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

_MENU_ACTIONS = st.components.v2.component(
    "menu_actions_v8",
    html='<div id="mt-menu-actions" hidden aria-hidden="true"></div>',
    css="#mt-menu-actions { display: none !important; height: 0; width: 0; }",
    js="""
export default function (component) {
  const { setTriggerValue } = component;
  const onAction = (event) => {
    const action = event && event.detail;
    if (
      action === "reload_data" ||
      action === "run_etl" ||
      action === "data_sources" ||
      action === "events"
    ) {
      setTriggerValue(action, Date.now());
    }
  };
  window.addEventListener("mt-menu-action", onAction);
  return () => window.removeEventListener("mt-menu-action", onAction);
}
""",
    isolate_styles=True,
)


def mount_menu_actions(
    *,
    on_reload_data: Callable[[], None] | None = None,
    on_run_etl: Callable[[], None] | None = None,
    on_data_sources: Callable[[], None] | None = None,
    on_events: Callable[[], None] | None = None,
    key: str = "mt_menu_actions_v8",
) -> None:
    """Mount the invisible menu-action bridge and wire Python callbacks."""

    def _on_reload_data_change() -> None:
        if on_reload_data is not None:
            on_reload_data()

    def _on_run_etl_change() -> None:
        if on_run_etl is not None:
            on_run_etl()

    def _on_data_sources_change() -> None:
        if on_data_sources is not None:
            on_data_sources()

    def _on_events_change() -> None:
        if on_events is not None:
            on_events()

    _MENU_ACTIONS(
        key=key,
        data={},
        width="content",
        height="content",
        on_reload_data_change=_on_reload_data_change,
        on_run_etl_change=_on_run_etl_change,
        on_data_sources_change=_on_data_sources_change,
        on_events_change=_on_events_change,
    )
