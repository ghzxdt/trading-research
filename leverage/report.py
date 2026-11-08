"""The Leverage tab page: a sortable table of every perp, then the index-perp studies and a data check.

It reuses the Indexes tab's page template (same look, charts, dark mode) but is its own page,
so nothing here mixes into the index findings.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from stage1.report import TEMPLATE, _health_html, _study_html, hub_nav, write_hub_index

from .build import MARKET_COLUMNS, NY
from validation import now_et

DEFAULT_TYPES = {"Index", "ETF", "Stock"}
TYPE_ORDER = ["Index", "ETF", "Stock", "Metal", "Energy", "Crypto"]


def _fmt(v, kind: str) -> str:
    """Python twin of the page's JS formatter, for the table as first drawn (and for no-JS readers)."""
    if kind == "text":
        return "" if v is None else str(v)
    if v is None or (isinstance(v, float) and not np.isfinite(v)) or v == "":
        return "–"
    if kind == "lev":
        return f"{v:.1f}x"
    if kind == "pct1":
        return f"{v * 100:.1f}%"
    if kind == "pct2":
        return f"{v * 100:.2f}%"
    if kind == "share":
        return f"{v * 100:.0f}%"
    if kind == "int":
        return f"{int(v):,}"
    if kind == "usd2":
        return f"-${abs(v):.2f}" if v < 0 else f"${v:.2f}"
    if kind == "usd_compact":
        for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(v) >= div:
                return f"${v / div:.1f}{suf}"
        return f"${v:.0f}"
    if kind == "date":
        t = pd.Timestamp(v)
        return f"{t:%b} {t.day}, {t.year}"
    return str(v)


def _json_value(v):
    if isinstance(v, (float, np.floating)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def _markets_html(rows: pd.DataFrame) -> str:
    keys = [c[0] for c in MARKET_COLUMNS]
    data = [{k: _json_value(r[k]) for k in keys + ["ticker", "status"]} for _, r in rows.iterrows()]
    cols = [{"key": k, "label": lab, "fmt": f, "help": h} for k, lab, f, h in MARKET_COLUMNS]
    types = [t for t in TYPE_ORDER if t in set(rows["type"])] + sorted(set(rows["type"]) - set(TYPE_ORDER))
    counts = rows[rows["status"] == "active"]["type"].value_counts()
    platforms = sorted(set(rows["platform"]))

    boxes = "".join(
        f'<label><input type="checkbox" name="type" value="{escape(t)}"{" checked" if t in DEFAULT_TYPES else ""}> {escape(t)} '
        f'<span class="muted">({int(counts.get(t, 0))})</span></label>' for t in types)
    plat = "".join(f'<option value="{escape(p)}">{escape(p)}</option>' for p in platforms)
    sorted_attr = ' aria-sort="descending"'
    head = "".join(
        f'<th scope="col"{sorted_attr if k == "max_leverage" else ""}><button type="button" data-key="{k}" title="{escape(h)}">{escape(lab)}</button></th>'
        for k, lab, f, h in MARKET_COLUMNS)

    def cell(r, k, f):
        if k == "name":
            return f'<td class="text">{escape(str(r["name"]))}<span class="ticker">{escape(str(r["ticker"]))}</span></td>'
        return f'<td class="{"text" if f == "text" else "num"}">{escape(_fmt(r[k], f))}</td>'

    shown = rows[(rows["status"] == "active") & rows["type"].isin(DEFAULT_TYPES)]
    body = "".join("<tr>" + "".join(cell(r, k, f) for k, _, f, _ in MARKET_COLUMNS) + "</tr>" for _, r in shown.iterrows())
    terms = "".join(f"<li><b>{escape(lab)}:</b> {escape(h)}.</li>" for _, lab, _, h in MARKET_COLUMNS)
    payload = json.dumps({"rows": data, "cols": cols}, separators=(",", ":")).replace("</", "<\\/")
    return f"""<section class="card" id="markets">
<div class="eyebrow">Every market</div>
<h2>Every perp, sorted by leverage</h2>
<p class="question">One row per market. Click a column name to sort by it (click again to flip). Tick the types you want to see.</p>
<div class="controls">
<fieldset><legend>Show</legend>{boxes}</fieldset>
<label>Platform <select id="f-platform"><option value="">All</option>{plat}</select></label>
<label><input type="checkbox" id="f-active" checked> Active only</label>
<span id="m-count" class="muted small" aria-live="polite">Showing {len(shown)} of {len(rows)}</span>
</div>
<div class="table-wrap"><table class="markets" id="markets-table"><caption>Perpetual futures by market</caption>
<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
<details><summary>What the columns mean</summary><ul class="small">{terms}</ul></details>
</section>
<script type="application/json" id="markets-data">{payload}</script>
<script>
(function () {{
  "use strict";
  const D = JSON.parse(document.getElementById("markets-data").textContent);
  const table = document.getElementById("markets-table");
  const tbody = table.querySelector("tbody");
  const count = document.getElementById("m-count");
  const state = {{ key: "max_leverage", dir: -1 }};
  const fmtOf = Object.fromEntries(D.cols.map((c) => [c.key, c.fmt]));
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmt(v, f) {{
    if (f === "text") return v === null || v === undefined ? "" : String(v);
    if (v === null || v === undefined || v === "") return "–";
    if (f === "lev") return v.toFixed(1) + "x";
    if (f === "pct1") return (v * 100).toFixed(1) + "%";
    if (f === "pct2") return (v * 100).toFixed(2) + "%";
    if (f === "share") return (v * 100).toFixed(0) + "%";
    if (f === "int") return Number(v).toLocaleString("en-US");
    if (f === "usd2") return (v < 0 ? "-$" : "$") + Math.abs(v).toFixed(2);
    if (f === "usd_compact") {{
      const a = Math.abs(v);
      if (a >= 1e9) return "$" + (v / 1e9).toFixed(1) + "B";
      if (a >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M";
      if (a >= 1e3) return "$" + (v / 1e3).toFixed(1) + "K";
      return "$" + v.toFixed(0);
    }}
    if (f === "date") {{ const [y, m, d] = v.split("-").map(Number); return MONTHS[m - 1] + " " + d + ", " + y; }}
    return String(v);
  }}
  function cmp(a, b) {{
    const x = a[state.key], y = b[state.key];
    const xe = x === null || x === undefined || x === "", ye = y === null || y === undefined || y === "";
    if (xe && ye) return 0;
    if (xe) return 1;   // blanks always last
    if (ye) return -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * state.dir;
    return String(x).localeCompare(String(y)) * state.dir;
  }}
  function render() {{
    const types = new Set([...document.querySelectorAll('input[name="type"]:checked')].map((e) => e.value));
    const plat = document.getElementById("f-platform").value;
    const active = document.getElementById("f-active").checked;
    const rows = D.rows.filter((r) => types.has(r.type) && (!plat || r.platform === plat) && (!active || r.status === "active"));
    rows.sort(cmp);
    tbody.replaceChildren();
    rows.forEach((r) => {{
      const tr = document.createElement("tr");
      D.cols.forEach((c) => {{
        const td = document.createElement("td");
        td.className = c.fmt === "text" ? "text" : "num";
        td.textContent = fmt(r[c.key], c.fmt);
        if (c.key === "name") {{
          const s = document.createElement("span"); s.className = "ticker"; s.textContent = r.ticker; td.appendChild(s);
        }}
        tr.appendChild(td);
      }});
      tbody.appendChild(tr);
    }});
    count.textContent = "Showing " + rows.length + " of " + D.rows.length;
    table.querySelectorAll("th").forEach((th) => {{
      const k = th.querySelector("button").dataset.key;
      if (k === state.key) th.setAttribute("aria-sort", state.dir < 0 ? "descending" : "ascending"); else th.removeAttribute("aria-sort");
    }});
  }}
  table.querySelectorAll("th button").forEach((b) => b.addEventListener("click", () => {{
    const k = b.dataset.key;
    if (state.key === k) state.dir = -state.dir;
    else {{ state.key = k; state.dir = fmtOf[k] === "text" || fmtOf[k] === "date" ? 1 : -1; }}
    render();
  }}));
  document.querySelectorAll('#markets input, #markets select').forEach((e) => e.addEventListener("change", render));
  render();
}})();
</script>"""


def build(rows: pd.DataFrame, studies: list[dict], health: dict, fetched: datetime, out_path: Path) -> Path:
    charts: dict = {}
    active = rows[rows["status"] == "active"]
    idx_names = ", ".join(active[active["type"].isin(["Index", "ETF"])]["name"])
    fetched = pd.Timestamp(fetched)
    fetched = fetched.tz_localize("UTC") if fetched.tzinfo is None else fetched
    fetched = fetched.tz_convert(NY)
    when = f"{fetched:%b} {fetched.day}, {fetched.year} {fetched:%I:%M %p} ET".replace(" 0", " ")
    head = [hub_nav("leverage")]
    if health["banner"]:
        head.append('<div class="banner" role="alert"><span class="chip warn"><span class="icon" aria-hidden="true">!</span>Data warning</span><ul>'
                    + "".join(f"<li>{escape(b)}</li>" for b in health["banner"]) + '</ul><a href="#health">See the data check</a></div>')
    sm = health["summary"]
    head += [
        "<header>",
        '<div class="eyebrow">Index research &middot; leverage</div>',
        "<h1>Perpetual futures: leverage, cost and risk by market</h1>",
        f'<p class="sub">Kalshi data as of {escape(when)} &middot; {len(rows)} markets ({len(active)} active) &middot; built {now_et():%b %d, %Y %I:%M %p} ET</p>',
        "</header>",
        '<section class="card">',
        "<h2>What this is</h2>",
        "<p>This tab is separate from the Indexes tab. It covers <b>perpetual futures</b> (&ldquo;perps&rdquo;): contracts that follow a market, never expire, "
        "and let you trade a position several times bigger than the cash you put up. The Indexes tab shows how the markets themselves behave; "
        "this tab shows what it costs and risks to trade them with leverage.</p>",
        '<dl class="terms">',
        "<dt>Published leverage</dt><dd>Exposure per dollar of collateral. Estimates vary by side and size; the reference column uses the smaller available published estimate and is not a recommendation.</dd>",
        "<dt>Proxy barrier</dt><dd>An uncalibrated fixed-entry-notional approximation for research. Actual liquidation can differ with the current mark, side, size, funding, fees and margin changes. Remaining collateral after a close is not necessarily zero.</dd>",
        "<dt>Funding</dt><dd>A transfer longs and shorts may pay each other on the product's funding schedule to keep the perp near its market. It's charged on the full position.</dd>",
        "<dt>Bid-ask spread</dt><dd>Full ask-minus-bid relative to midpoint: approximately a round-trip spread cost at unchanged quotes. One side versus midpoint costs half the quoted spread, before fees and impact.</dd>",
        "<dt>Open interest</dt><dd>Dollar notional of open positions. This is not an execution-depth or liquidity guarantee.</dd>",
        "</dl>",
        f"<p>Index perps in this saved snapshot: <b>{escape(idx_names)}</b>. Use the actual sample dates and record counts to judge history length.</p>",
        f'<p class="muted small">Data check: <b>{sm["warn"]}</b> warning{"s" if sm["warn"] != 1 else ""}, <b>{sm["note"]}</b> note{"s" if sm["note"] != 1 else ""}, '
        f'{sm["ok"]} OK. <a href="#health">See what was found</a>.</p>',
        '<nav class="toc" aria-label="Sections"><a href="#markets">Every perp, sorted by leverage</a>'
        + "".join(f'<a href="#{s["id"]}">{s["number"]}. {escape(s["title"])}</a>' for s in studies) + "</nav>",
        "</section>",
    ]
    body = "\n".join(head) + "\n" + _markets_html(rows) + "\n" + "\n".join(_study_html(s, charts) for s in studies)
    body += "\n" + _health_html(health, "Checks on the Kalshi data")
    body += """
<footer class="card">
<h3>Where the data comes from</h3>
<ul>
<li>Kalshi's public market-data API (no account needed): the market list, risk settings, every funding payment, and hourly prices for the index perps. Saved in data/raw/kalshi/.</li>
<li>Each run also adds the market list to data/kalshi/snapshots.csv, because Kalshi doesn't serve past spreads or open interest.</li>
<li>Proxy barrier history uses the corresponding ETF daily highs and lows from the Indexes tab's data (Yahoo Finance).</li>
</ul>
<h3>Limits to keep in mind</h3>
<ul>
<li>Published leverage estimates depend on side, size and changing risk settings. The barriers shown here approximate initial cash minus maintenance on entry notional. They are uncalibrated proxy research values, not certified liquidation quotes or sizing instructions. Initial margin equals maintenance times the published multiplier, but that relationship alone does not determine actual liquidation prices.</li>
<li>ETF barrier-hit frequencies cover regular-session extrema only. They are not measured perp liquidation probabilities. Overnight paths, mark/basis differences, fees, funding and margin changes can materially change outcomes. Confirm actual broker liquidation quotes before any trade; automatic sizing remains blocked.</li>
<li>US500 and US Tech 100 follow their own indexes, not SPY and QQQ exactly.</li>
<li>Trading Kalshi perps needs an approved margin account. This is research, not financial advice.</li>
</ul>
</footer>"""
    chart_json = json.dumps(charts, separators=(",", ":")).replace("</", "<\\/")
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", f"Leverage: perps by market ({fetched:%b %d, %Y})")
            .replace("{{BODY}}", body)
            .replace("{{CHART_DATA}}", chart_json))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    write_hub_index(out_path.parent)
    return out_path
