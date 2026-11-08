"""Turn the study results into one self-contained HTML page (no internet needed to open it)."""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

TEMPLATE = Path(__file__).with_name("report_template.html")

# The hub: one tab per part of the app. Each part is its own page, so they never mix.
TABS = [("today", "today.html", "Today"), ("indexes", "report.html", "Indexes"), ("tickers", "tickers.html", "Tickers"), ("leverage", "leverage.html", "Leverage (perps)"),
        ("gex", "gex.html", "GEX / DIX"), ("compare", "monitor.html", "Original vs fixed"),
        ("backtests", "backtests.html", "Backtests"), ("paper", "paper.html", "Paper monitor"),
        ("quality", "quality.html", "Data quality"), ("jobs", "jobs.html", "Jobs & macro")]


def hub_nav(active: str) -> str:
    current = ' aria-current="page"'
    # The GEX / DIX tab carries a Cold/Warm/Hot badge, filled in on page load from output/gex_status.json.
    badge = '<span class="tab-badge" data-gex-badge hidden></span>'
    links = "".join(
        f'<a href="{href}"{current if key == active else ""}>{escape(label)}{badge if key == "gex" else ""}</a>' for key, href, label in TABS
    )
    controls = """<div class="card" style="padding:10px 16px;margin-top:8px"><button data-refresh="/api/refresh">Refresh data + validate</button> <button data-refresh="/api/rebuild">Rebuild saved data</button> <button onclick="location.reload()">Reload view</button> <span data-build-status>Local research dashboard</span></div>
<script>(function(){const label=document.querySelector('[data-build-status]');const buttons=document.querySelectorAll('[data-refresh]');async function status(){try{const r=await fetch('/api/status');if(!r.ok)return;const s=await r.json();label.textContent=s.build?s.build.message:'Ready';buttons.forEach(b=>b.disabled=s.busy);if(s.busy)setTimeout(status,2000);}catch(e){label.textContent='Open through START_APP.cmd to refresh.';}}buttons.forEach(b=>b.addEventListener('click',async()=>{buttons.forEach(x=>x.disabled=true);label.textContent='Starting validated build...';try{const r=await fetch(b.dataset.refresh,{method:'POST',headers:{'X-Hub':'1'}});const s=await r.json();if(!r.ok)throw Error(s.error);status();}catch(e){label.textContent=e.message;buttons.forEach(x=>x.disabled=false);}}));status();})();</script>"""
    return f'<nav class="hub-tabs" aria-label="App sections">{links}</nav>' + controls


def write_hub_index(out_dir: Path) -> None:
    """output/index.html opens the hub on the Today workspace."""
    out_dir.mkdir(parents=True, exist_ok=True)
    links = " &middot; ".join(f'<a href="{href}">{escape(label)}</a>' for _, href, label in TABS)
    (out_dir / "index.html").write_text(
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Index research</title>'
        '<meta http-equiv="refresh" content="0; url=today.html"></head>'
        f'<body><p>Opening Today&hellip; {links}</p></body></html>', encoding="utf-8")

ICONS = {"edge": "✓", "hint": "~", "none": "–", "fact": "i", "ok": "✓", "note": "i", "warn": "!"}
HEALTH_LABELS = {"ok": "OK", "note": "Note", "warn": "Warning"}


def _chip(verdict: str, label: str) -> str:
    return f'<span class="chip {verdict}"><span class="icon" aria-hidden="true">{ICONS[verdict]}</span>{escape(label)}</span>'


def _table(tbl: dict) -> str:
    head = "".join(f"<th scope=\"col\">{escape(str(c))}</th>" for c in tbl["columns"])
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in tbl["rows"]
    )
    return (f'<div class="table-wrap"><table><caption>{escape(tbl["title"])}</caption>'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")


def _chart_table(spec: dict) -> dict:
    """Every chart gets a plain table twin, so no value is hidden behind a hover."""
    from .studies import mult, num, pct

    def f(v):
        if v is None:
            return "-"
        def dollars(x):
            return f"${x:.3g}" if 0 < abs(x) < .01 else f"${x:,.2f}"
        return {"pct": lambda x: pct(x, 2), "mult": mult, "dollar": dollars}.get(spec.get("format"), num)(v)

    names = [s["name"] for s in spec["series"]]
    if spec["type"] == "bar":
        rows = [[c] + [f(s["values"][i]) for s in spec["series"]] for i, c in enumerate(spec["categories"])]
        return {"title": spec["title"], "columns": [""] + names, "rows": rows}
    x = spec["x"]
    if spec.get("xUnit") == "day":
        rows = [[x[i]] + [f(s["values"][i]) for s in spec["series"]] for i in range(len(x))]
        return {"title": spec["title"], "columns": ["Date"] + names, "rows": rows}
    # Line charts: one row per year (last week of each year), plus the latest point.
    idx = [i for i in range(len(x)) if i == len(x) - 1 or x[i][:4] != x[i + 1][:4]]
    rows = [[x[i]] + [f(s["values"][i]) for s in spec["series"]] for i in idx]
    return {"title": spec["title"] + " (end of each year)", "columns": ["Week of"] + names, "rows": rows}


def _study_html(s: dict, charts: dict) -> str:
    out = [f'<section class="card study" id="{s["id"]}">',
           f'<div class="eyebrow">Question {s["number"]}</div>',
           f'<h2>{escape(s["title"])}</h2>',
           f'<p class="question">{escape(s["question"])}</p>',
           '<div class="tiles">']
    for tile in s["tiles"]:
        out.append(f'<div class="tile"><div class="label">{escape(tile["label"])}</div>'
                   f'<div class="value">{escape(tile["value"])}</div><div class="note">{escape(tile["note"])}</div></div>')
    out.append("</div><ul class=\"findings\">")
    for fnd in s["findings"]:
        out.append(f'<li><div>{_chip(fnd["verdict"], fnd["label"])}</div><div><div class="headline">{escape(fnd["headline"])}</div>'
                   f'<div class="detail">{escape(fnd["detail"])}</div></div></li>')
    out.append("</ul>")
    if s.get("notes"):
        out.append(f'<p class="muted small">{escape(s["notes"])}</p>')
    for spec in s["charts"]:
        charts[spec["id"]] = spec
        out.append(f'<figure><figcaption><div class="title">{escape(spec["title"])}</div>'
                   f'<div class="subtitle">{escape(spec.get("subtitle", ""))}</div></figcaption>'
                   f'<div class="chart" data-chart="{spec["id"]}"></div>'
                   f'<details><summary>Show the numbers</summary>{_table(_chart_table(spec))}</details></figure>')
    if s["tables"] and s.get("show_tables"):
        out.extend(_table(tbl) for tbl in s["tables"])  # tables are the main content here
    elif s["tables"]:
        out.append("<details><summary>More numbers</summary>")
        out.extend(_table(tbl) for tbl in s["tables"])
        out.append("</details>")
    out.append("</section>")
    return "\n".join(out)


def _health_html(health: dict, heading: str = "What looked wrong in the free data, and what was done") -> str:
    rows = "".join(
        f'<tr><td>{_chip(i["level"], HEALTH_LABELS[i["level"]])}</td><td>{escape(i["check"])}</td>'
        f'<td>{escape(i["result"])}</td><td>{escape(i["action"])}</td></tr>'
        for i in health["items"]
    )
    return ('<section class="card" id="health"><div class="eyebrow">Data check</div><h2>' + escape(heading) + '</h2>'
            '<p class="question">Run on every build. Warnings also show at the top of the report.</p>'
            '<div class="table-wrap"><table class="health"><caption>Checks on this run</caption>'
            '<thead><tr><th scope="col">Status</th><th scope="col">Check</th><th scope="col">Result</th><th scope="col">What was done</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div></section>")


def build(studies: list[dict], tests_run: int, table: pd.DataFrame, out_path: Path, health: dict | None = None) -> Path:
    charts: dict = {}
    first, last = table.index[0], table.index[-1]
    all_findings = [f for s in studies for f in s["findings"]]
    count = {k: sum(1 for f in all_findings if f["verdict"] == k) for k in ("edge", "hint", "none", "fact")}
    edges = [(s, f) for s in studies for f in s["findings"] if f["verdict"] == "edge" and f.get("kind") != "size"]
    sizes = [(s, f) for s in studies for f in s["findings"] if f["verdict"] == "edge" and f.get("kind") == "size"]
    expected_by_luck = tests_run * 0.05

    head = [hub_nav("indexes")]
    if health and health["banner"]:
        head.append('<div class="banner" role="alert">' + _chip("warn", "Data warning") + "<ul>"
                    + "".join(f"<li>{escape(b)}</li>" for b in health["banner"]) + '</ul><a href="#health">See the data check</a></div>')
    head += [
        '<header>',
        '<div class="eyebrow">Index research &middot; stage 1</div>',
        "<h1>How SPY, QQQ and friends have normally behaved</h1>",
        f'<p class="sub">Data from {first:%b %d, %Y} through {last:%b %d, %Y} &middot; {len(table):,} trading days &middot; built {datetime.now():%b %d, %Y %I:%M %p}</p>',
        "</header>",
        '<section class="card">',
        "<h2>What this is</h2>",
        "<p>A look back at how the big index ETFs have usually behaved. It doesn't predict tomorrow and doesn't suggest trades. "
        "It sets the <b>normal</b> that any future idea has to beat. Every finding has a label:</p>",
        '<ul class="findings">',
        f'<li><div>{_chip("fact", "Fact")}</div><div class="detail">A description of what happened. Nothing to bet on by itself.</div></li>',
        f'<li><div>{_chip("edge", "Possible edge")}</div><div class="detail">Beat the luck test <i>and</i> pointed the same way in at least 3 of 4 time periods. Worth testing properly, with trading costs, in stage 2. Not proof.</div></li>',
        f'<li><div>{_chip("hint", "Weak hint")}</div><div class="detail">Something may be there, but luck could easily explain it, or it only showed up in one stretch of years.</div></li>',
        f'<li><div>{_chip("none", "No edge")}</div><div class="detail">Random days looked just as different. Treat it as luck and drop it.</div></li>',
        "</ul>",
        '<div class="score">',
        f'{_chip("edge", "Possible edge")} <span><b>{count["edge"]}</b></span>',
        f'{_chip("hint", "Weak hint")} <span><b>{count["hint"]}</b></span>',
        f'{_chip("none", "No edge")} <span><b>{count["none"]}</b></span>',
        f'{_chip("fact", "Fact")} <span><b>{count["fact"]}</b></span>',
        "</div>",
        f'<p class="muted small">Honesty check: this report ran <b>{tests_run}</b> luck tests. At the bar used here, about '
        f'<b>{expected_by_luck:.1f}</b> would pass by pure chance even if nothing were real. So a "possible edge" is a lead to test, not a result.</p>',
    ]
    if health:
        sm = health["summary"]
        head.append(f'<p class="muted small">Data check: <b>{sm["warn"]}</b> warning{"s" if sm["warn"] != 1 else ""}, '
                    f'<b>{sm["note"]}</b> note{"s" if sm["note"] != 1 else ""}, {sm["ok"]} OK. <a href="#health">See what was found</a>.</p>')
    if edges:
        head.append("<p><b>Leads worth testing in stage 2</b> (which way the market went):</p><ul class=\"edges-list\">")
        head.extend(f'<li><a href="#{s["id"]}">{escape(f["headline"])}</a></li>' for s, f in edges)
        head.append("</ul>")
    if sizes:
        head.append("<p><b>Size effects that beat luck</b> (how big moves got; useful for sizing and stops, not for picking a direction):</p><ul class=\"edges-list\">")
        head.extend(f'<li><a href="#{s["id"]}">{escape(f["headline"])}</a></li>' for s, f in sizes)
        head.append("</ul>")
    head.append('<nav class="toc" aria-label="Sections">')
    head.extend(f'<a href="#{s["id"]}">{s["number"]}. {escape(s["title"])}</a>' for s in studies)
    head.append("</nav></section>")

    body = "\n".join(head) + "\n" + "\n".join(_study_html(s, charts) for s in studies)
    if health:
        body += "\n" + _health_html(health)
    body += """
<footer class="card">
<h3>Where the data comes from</h3>
<ul>
<li>ETF prices: Yahoo Finance (free, unofficial), adjusted for splits and dividends.</li>
<li>VIX, VIX9D, VIX3M, VVIX: Cboe's public daily history.</li>
<li>Treasury yields: FRED (St. Louis Fed). Shifted one day, because they're published the day after.</li>
<li>Jobs and CPI report dates: BLS release archives. Fed decision dates: federalreserve.gov. Saved in data/events/events.csv.</li>
</ul>
<h3>Limits to keep in mind</h3>
<ul>
<li>No trading costs, spreads or slippage are included anywhere. Real results would be lower.</li>
<li>Daily prices only. Nothing here looks inside the day (VWAP, opening range). That needs minute data in stage 2.</li>
<li>Free data can have small errors, especially old opening prices. The data check above lists what was found and fixed.</li>
<li>The past is not a promise. Patterns fade once enough people trade them.</li>
<li>This is research, not financial advice.</li>
</ul>
</footer>"""

    chart_json = json.dumps(charts, separators=(",", ":")).replace("</", "<\\/")
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", f"Index research, stage 1 ({last:%b %d, %Y})")
            .replace("{{BODY}}", body)
            .replace("{{CHART_DATA}}", chart_json))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    write_hub_index(out_path.parent)
    return out_path
