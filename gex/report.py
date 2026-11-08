"""The GEX / DIX tab page: the Cold/Warm/Hot refresh bar and buttons, today's reading, history, data check."""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

from stage1.report import TEMPLATE, _health_html, _study_html, hub_nav, write_hub_index

from .data import SOURCE_PAGE, _day


def _refresh_html(status: dict, copy_through: str | None) -> str:
    temp = status.get("temp")
    segs = "".join(
        f'<div class="temp-seg{" on" if temp == key else ""}"><b>{label}</b><span>{escape(desc)}</span></div>'
        for key, label, desc in [("cold", "Cold", "calm: no need to refresh"), ("warm", "Warm", "some stress: optional"),
                                 ("hot", "Hot", "stressed: refresh")])
    reasons = "".join(f"<li>{escape(r)}</li>" for r in status.get("reasons", []))
    copy = f"Your copy runs through <b>{escape(_day(copy_through))}</b>." if copy_through else "You don't have a copy yet."
    return f"""<section class="card" id="refresh">
<div class="eyebrow">Refresh</div>
<h2>{escape(status.get("label", ""))}</h2>
<div class="temp-bar" role="img" aria-label="Refresh level: {escape((temp or 'unknown').capitalize())}">{segs}</div>
<p class="question">{copy} The level comes from what the other tabs already pulled; this tab only changes when you update it.</p>
<ul class="small">{reasons}</ul>
<div class="refresh-steps">
<a class="btn" href="{SOURCE_PAGE}" target="_blank" rel="noopener noreferrer">1. Get the file</a>
<span class="muted small">opens SqueezeMetrics; click <b>CSV</b> there to download it</span>
</div>
<div class="refresh-steps">
<button type="button" class="btn" id="gex-update" disabled>2. Update</button>
<span class="muted small" id="gex-msg" aria-live="polite">Checking for the helper&hellip;</span>
</div>
<details><summary>Without the helper</summary>
<p class="small">The Update button needs the helper running: <code>.venv/Scripts/python hub_server.py</code>, then open <code>http://localhost:8765</code>.
Or, after downloading, run <code>.venv/Scripts/python run_gex.py --import</code> and reload this page.</p></details>
</section>
<script>
(function () {{
  "use strict";
  const btn = document.getElementById("gex-update"), msg = document.getElementById("gex-msg");
  fetch("/api/status", {{ cache: "no-store" }}).then((r) => {{
    if (!r.ok) throw new Error();
    btn.disabled = false;
    msg.textContent = "After the download finishes, click Update. The app picks the file up from your Downloads folder.";
  }}).catch(() => {{
    msg.textContent = "The Update button needs the helper (see 'Without the helper' below).";
  }});
  btn.addEventListener("click", () => {{
    btn.disabled = true;
    msg.textContent = "Looking in Downloads and rebuilding this tab...";
    fetch("/api/gex/update", {{ method: "POST", headers: {{ "X-Hub": "1" }} }})
      .then((r) => r.json())
      .then((j) => {{
        if (j.ok) {{ msg.textContent = j.message + " Reloading..."; setTimeout(() => location.reload(), 900); }}
        else {{ msg.textContent = j.error; btn.disabled = false; }}
      }})
      .catch(() => {{ msg.textContent = "The helper didn't answer. Is it still running?"; btn.disabled = false; }});
  }});
}})();
</script>"""


def build(studies: list[dict], health: dict, status: dict, copy_through: str | None, market_through, out_path: Path) -> Path:
    charts: dict = {}
    sm = health["summary"]
    head = [
        hub_nav("gex"),
        "<header>",
        '<div class="eyebrow">Index research &middot; GEX / DIX</div>',
        "<h1>GEX and DIX: dealer positioning and dark-pool activity</h1>",
        f'<p class="sub">Your copy through {escape(_day(copy_through)) if copy_through else "&ndash;"} &middot; market data through '
        f'{escape(_day(market_through)) if market_through is not None else "&ndash;"} &middot; built {datetime.now():%b %d, %Y %I:%M %p}</p>',
        "</header>",
        _refresh_html(status, copy_through),
    ]
    if studies:
        head.append('<section class="card"><h2>What this is</h2>'
                    "<p><b>GEX</b> estimates how options dealers are positioned. Below zero, they tend to trade with the market and add to moves; "
                    "above zero, they tend to dampen them. <b>DIX</b> measures dark-pool activity. Both come from SqueezeMetrics, published after each close. "
                    "This tab reads the Indexes tab (VIX, prices) and the Leverage tab (cushions); neither of those depends on it.</p>"
                    f'<p class="muted small">Data check: <b>{sm["warn"]}</b> warnings, <b>{sm["note"]}</b> notes, {sm["ok"]} OK. <a href="#health">See it</a>.</p>'
                    '<nav class="toc" aria-label="Sections">' + "".join(f'<a href="#{s["id"]}">{s["number"]}. {escape(s["title"])}</a>' for s in studies)
                    + "</nav></section>")
    body = "\n".join(head) + "\n" + "\n".join(_study_html(s, charts) for s in studies)
    body += "\n" + _health_html(health, "Checks on this tab's data")
    body += """
<footer class="card">
<h3>Where the data comes from</h3>
<ul>
<li>GEX and DIX: SqueezeMetrics' free CSV, downloaded by you in your browser and copied in from your Downloads folder. Their terms bar systematically retrieving data to build a database, so the app never downloads it.</li>
<li>VIX, prices and day types: the Indexes tab's daily table. Liquidation cushions: the Leverage tab.</li>
</ul>
<h3>Limits</h3>
<ul>
<li>SqueezeMetrics doesn't publish how GEX or DIX are calculated, so they can't be checked independently.</li>
<li>Each value is treated as known only before the next session, because it's published after the close.</li>
<li>This is research, not financial advice.</li>
</ul>
</footer>"""
    chart_json = json.dumps(charts, separators=(",", ":")).replace("</", "<\\/")
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", "GEX / DIX" + (f" ({_day(copy_through)})" if copy_through else ""))
            .replace("{{BODY}}", body)
            .replace("{{CHART_DATA}}", chart_json))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    write_hub_index(out_path.parent)
    return out_path
