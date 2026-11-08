"""Render Today without collecting data or creating paper trades."""
from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from html import escape
from numbers import Integral, Real
from pathlib import Path


TEMPLATE = Path(__file__).with_name("template.html")


def json_safe(value):
    """Strict JSON data; unknown/nonfinite observations stay null."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def embedded_json(value):
    """Escape HTML syntax in JSON inside a script element."""
    return (json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False,
                       sort_keys=True, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def build(root, out, state=None):
    """Write today.html, today_state.json, and the Today component manifest."""
    root, out = Path(root), Path(out)
    if state is None:
        from terminal_state import build_state
        state = build_state(root, symbol="SPY", as_of=os.environ.get("APP_AS_OF"))
    if not isinstance(state, Mapping):
        raise ValueError("Today state must be a JSON object")
    state = json_safe(state)
    from stage1.report import hub_nav
    from validation import write_component_manifest

    rendered = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "{{HUB_NAV}}": hub_nav("today"),
        "{{STATE}}": embedded_json(state),
        "{{SYMBOL}}": escape(str(state.get("symbol") or "SPY")),
        "{{AS_OF}}": escape(str(state.get("as_of") or "Unavailable")),
    }
    rendered = re.sub(r"\{\{(?:HUB_NAV|STATE|SYMBOL|AS_OF)\}\}",
                      lambda match: replacements[match.group()], rendered)
    out.mkdir(parents=True, exist_ok=True)
    (out / "today.html").write_text(rendered, encoding="utf-8")
    (out / "today_state.json").write_text(
        json.dumps(state, ensure_ascii=False, allow_nan=False, sort_keys=True,
                   indent=2) + "\n", encoding="utf-8")
    write_component_manifest("today", out, {
        "state_schema_version": state.get("schema_version"),
        "symbol": state.get("symbol"), "state_as_of": state.get("as_of"),
        "readonly_render": True,
    })
    return out / "today.html"
