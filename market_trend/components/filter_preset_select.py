"""Custom filter preset picker (Streamlit Custom Components v2)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import streamlit as st

_CSS = """
@font-face {
  font-family: IRANSans-Edit;
  src: url("/app/static/fonts/IRANSans-Edit.ttf") format("truetype");
  font-weight: normal;
  font-style: normal;
  font-display: swap;
}
#fps-root {
  width: 100%;
  min-width: 12rem;
  font-family: IRANSans-Edit, Tahoma, sans-serif;
  color: var(--st-text-color, inherit);
  direction: rtl;
  position: relative;
}
#fps-root * {
  font-family: IRANSans-Edit, Tahoma, sans-serif;
  box-sizing: border-box;
}
#fps-root .fps-control {
  width: 100%;
  min-height: 2.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.35rem 0.75rem;
  background: var(--st-secondary-background-color, #f8f9fb);
  border: 1px solid var(--st-border-color, rgba(49, 51, 63, 0.2));
  border-radius: 0.5rem;
  color: var(--st-text-color, inherit);
  cursor: pointer;
  user-select: none;
}
#fps-root .fps-control:focus {
  outline: 2px solid color-mix(in srgb, var(--st-primary-color, #ff4b4b) 45%, transparent);
  outline-offset: 1px;
}
#fps-root .fps-label {
  flex: 1 1 auto;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.95rem;
  line-height: 1.4;
}
#fps-root .fps-caret {
  flex: 0 0 auto;
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 5px 5px 0 5px;
  border-color: var(--st-text-color, #31333f) transparent transparent transparent;
  opacity: 0.55;
}
#fps-root.is-open .fps-caret {
  border-width: 0 5px 5px 5px;
  border-color: transparent transparent var(--st-text-color, #31333f) transparent;
}
#fps-root .fps-dropdown {
  display: none;
  position: absolute;
  top: calc(100% + 0.25rem);
  right: 0;
  left: 0;
  z-index: 1000;
  background: var(--st-background-color, #fff);
  border: 1px solid var(--st-border-color, rgba(49, 51, 63, 0.2));
  border-radius: 0.5rem;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  max-height: 16rem;
  overflow: auto;
}
#fps-root.is-open .fps-dropdown {
  display: block;
}
#fps-root .fps-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 5px 0.65rem;
  cursor: pointer;
  direction: rtl;
}
#fps-root .fps-option:hover,
#fps-root .fps-option.is-active {
  background: color-mix(in srgb, var(--st-primary-color, #ff4b4b) 12%, transparent);
}
#fps-root .fps-option-label {
  flex: 1 1 auto;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.95rem;
  line-height: 1.4;
}
#fps-root .fps-delete {
  flex: 0 0 auto;
  border: none;
  background: transparent;
  color: var(--st-text-color, inherit);
  opacity: 0.45;
  cursor: pointer;
  font-size: 1.1rem;
  line-height: 1;
  padding: 0.15rem 0.35rem;
  border-radius: 0.25rem;
}
#fps-root .fps-delete:hover {
  opacity: 1;
  background: color-mix(in srgb, var(--st-primary-color, #ff4b4b) 18%, transparent);
}
#fps-root .fps-empty {
  padding: 0.65rem;
  text-align: right;
  opacity: 0.7;
  font-size: 0.95rem;
}
"""

_JS = """
const _fpsInstances = new WeakMap();

function _fpsOptionsKey(options, placeholder, emptyLabel) {
  return JSON.stringify({
    options: options || [],
    placeholder: placeholder,
    emptyLabel: emptyLabel,
  });
}

function _fpsEscape(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export default function (component) {
  const data = component.data;
  const parentElement = component.parentElement;
  const setTriggerValue = component.setTriggerValue;
  const root = parentElement.querySelector("#fps-root");
  if (!root) return;

  const options = Array.isArray(data && data.options)
    ? data.options.map(String)
    : [];
  const value = data && data.value ? String(data.value) : "";
  const placeholder =
    data && data.placeholder ? String(data.placeholder) : "Select filter";
  const emptyLabel =
    data && data.empty_label
      ? String(data.empty_label)
      : "No saved filters";
  const nextKey = _fpsOptionsKey(options, placeholder, emptyLabel);

  let state = _fpsInstances.get(parentElement);
  if (state && state.key !== nextKey) {
    if (state.onDocClick) {
      document.removeEventListener("mousedown", state.onDocClick, true);
    }
    root.replaceChildren();
    root.classList.remove("is-open");
    _fpsInstances.delete(parentElement);
    state = null;
  }

  if (!state) {
    root.innerHTML =
      '<button type="button" class="fps-control" aria-haspopup="listbox" aria-expanded="false">' +
      '<span class="fps-label"></span><span class="fps-caret" aria-hidden="true"></span>' +
      "</button>" +
      '<div class="fps-dropdown" role="listbox"></div>';

    const control = root.querySelector(".fps-control");
    const labelEl = root.querySelector(".fps-label");
    const dropdown = root.querySelector(".fps-dropdown");

    function setOpen(open) {
      root.classList.toggle("is-open", open);
      control.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function renderDropdown() {
      if (options.length === 0) {
        dropdown.innerHTML =
          '<div class="fps-empty">' + _fpsEscape(emptyLabel) + "</div>";
        return;
      }
      dropdown.innerHTML = options
        .map(function (name) {
          return (
            '<div class="fps-option" role="option" data-value="' +
            _fpsEscape(name) +
            '">' +
            '<span class="fps-option-label">' +
            _fpsEscape(name) +
            "</span>" +
            '<button type="button" class="fps-delete" data-value="' +
            _fpsEscape(name) +
            '" aria-label="Delete" tabindex="-1">x</button>' +
            "</div>"
          );
        })
        .join("");
    }

    function syncLabel(current) {
      labelEl.textContent = current || placeholder;
    }

    control.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(!root.classList.contains("is-open"));
    });

    dropdown.addEventListener("click", function (event) {
      const target = event.target;
      if (!target || !target.closest) return;
      const del = target.closest(".fps-delete");
      if (del) {
        event.preventDefault();
        event.stopPropagation();
        const name = del.getAttribute("data-value");
        if (name) setTriggerValue("deleted", name);
        setOpen(false);
        return;
      }
      const opt = target.closest(".fps-option");
      if (!opt) return;
      event.preventDefault();
      event.stopPropagation();
      const name = opt.getAttribute("data-value");
      if (name) {
        syncLabel(name);
        setTriggerValue("selected", name);
      }
      setOpen(false);
    });

    const onDocClick = function (event) {
      if (!root.classList.contains("is-open")) return;
      const path = event.composedPath ? event.composedPath() : [];
      if (path.indexOf(root) >= 0) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick, true);

    renderDropdown();
    state = {
      key: nextKey,
      labelEl: labelEl,
      syncLabel: syncLabel,
      onDocClick: onDocClick,
      value: "",
    };
    _fpsInstances.set(parentElement, state);
    syncLabel(value && options.indexOf(value) >= 0 ? value : "");
    state.value = value && options.indexOf(value) >= 0 ? value : "";
  } else {
    const current = value && options.indexOf(value) >= 0 ? value : "";
    if (current !== state.value) {
      state.syncLabel(current);
      state.value = current;
    }
  }

  return function () {
    const existing = _fpsInstances.get(parentElement);
    if (!existing) return;
    if (existing.onDocClick) {
      document.removeEventListener("mousedown", existing.onDocClick, true);
    }
    _fpsInstances.delete(parentElement);
  };
}
"""

_FILTER_PRESET_SELECT = st.components.v2.component(
    "filter_preset_select_v2",
    html='<div id="fps-root"></div>',
    css=_CSS,
    js=_JS,
    isolate_styles=True,
)


def filter_preset_select(
    options: Sequence[str],
    *,
    value: str | None = None,
    placeholder: str = "انتخاب فیلتر",
    key: str = "filter_preset_select",
    on_select: Callable[[str], None] | None = None,
    on_delete: Callable[[str], None] | None = None,
    width: int | str = 280,
):
    """Mount a filter-preset select with per-option delete."""

    def _on_selected_change() -> None:
        payload = st.session_state.get(key, {})
        name = payload.get("selected") if isinstance(payload, dict) else None
        if name and on_select is not None:
            on_select(str(name))

    def _on_deleted_change() -> None:
        payload = st.session_state.get(key, {})
        name = payload.get("deleted") if isinstance(payload, dict) else None
        if name and on_delete is not None:
            on_delete(str(name))

    return _FILTER_PRESET_SELECT(
        key=key,
        data={
            "options": list(options),
            "value": value or "",
            "placeholder": placeholder,
            "empty_label": "فیلتر ذخیره‌شده‌ای نیست",
        },
        width=width,
        height="content",
        on_selected_change=_on_selected_change,
        on_deleted_change=_on_deleted_change,
    )
