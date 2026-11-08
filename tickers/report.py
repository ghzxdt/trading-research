"""Tickers tab pages: an overview (tickers.html) and one page per ETF (ticker_SPY.html, ...)."""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from pathlib import Path

from stage1.report import TEMPLATE, _health_html, _study_html, hub_nav, write_hub_index
from stage1.studies import pct, share

from .build import CATEGORIES, NAMES, _day, pct_dd
from .news import when_et


def subnav(active: str) -> str:
    links = ['<a href="tickers.html"' + (' aria-current="page"' if active == "all" else "") + ">All tickers</a>"]
    for _, tks in CATEGORIES:
        links.append('<span class="subnav-sep" aria-hidden="true"></span>')
        for tk in tks:
            links.append(f'<a href="ticker_{tk}.html"' + (' aria-current="page"' if active == tk else "") + f">{tk}</a>")
    return '<nav class="subnav" aria-label="Tickers">' + "".join(links) + "</nav>"


def news_html(items: list[dict], title: str, empty: str, limit: int = 10) -> str:
    if not items:
        return f'<h3>{escape(title)}</h3><p class="muted small">{escape(empty)}</p>'
    rows = "".join(
        f'<li><a href="{escape(i["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{escape(i["title"])}</a>'
        f'<span class="news-meta">{escape(i.get("publisher", ""))}{" &middot; " if i.get("publisher") and i.get("time") else ""}{escape(when_et(i.get("time", "")))}</span></li>'
        for i in items[:limit])
    return f'<h3>{escape(title)}</h3><ul class="news">{rows}</ul>'


def calendar_html(cal: list[dict]) -> str:
    if not cal:
        return '<p class="muted small">No scheduled events in the next 45 days in the events file.</p>'
    rows = "".join(f"<tr><td>{escape(_day(c['date']))} ({c['date']:%a})</td><td>{escape(c['what'])}</td></tr>" for c in cal)
    return ('<div class="table-wrap"><table class="health"><caption>Next 45 days</caption>'
            f'<thead><tr><th scope="col">Date</th><th scope="col">Event</th></tr></thead><tbody>{rows}</tbody></table></div>')


def _page(title: str, body: str, charts: dict, out_path: Path) -> Path:
    chart_json = json.dumps(charts, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("{{TITLE}}", title).replace("{{BODY}}", body).replace("{{CHART_DATA}}", chart_json)
    out_path.write_text(html, encoding="utf-8")
    return out_path


FOOTER = """
<footer class="card">
<h3>Where the data comes from</h3>
<ul>
<li>Prices and volume: the Indexes tab's daily table (Yahoo Finance, adjusted for splits and dividends), since 2010.</li>
<li>Headlines: Yahoo Finance, through the yfinance package (headlines and links only), and the Federal Reserve's official press-release feed. Saved in data/raw/news/.</li>
<li>Related readings: the Leverage tab (Kalshi perps) and your GEX/DIX file. Read-only: this tab never changes them.</li>
</ul>
<h3>Limits</h3>
<ul>
<li>Per-ticker numbers are descriptive. The luck-tested versions (SPY-based) are on the Indexes tab.</li>
<li>Order flow here means daily stand-ins (volume, where it closed in its range, the A/D line). Trade-by-trade flow and order books aren't free for these ETFs.</li>
<li>News is whatever Yahoo lists for the ticker; it can include promotional or prediction-market pieces. Read the source before acting on anything.</li>
<li>This is research, not financial advice.</li>
</ul>
</footer>"""


def build_ticker(tk: str, studies: list[dict], news: dict, cal: list[dict], health: dict, asof, out_dir: Path) -> Path:
    charts: dict = {}
    head = [hub_nav("tickers"), subnav(tk), "<header>", f'<div class="eyebrow">Tickers &middot; {escape(tk)}</div>',
            f"<h1>{escape(tk)}: {escape(NAMES[tk])}</h1>",
            f'<p class="sub">Prices through {escape(_day(asof))} &middot; built {datetime.now():%b %d, %Y %I:%M %p}</p>',
            "</header>",
            '<nav class="toc card" aria-label="Sections">' + "".join(f'<a href="#{s["id"]}">{s["number"]}. {escape(s["title"])}</a>' for s in studies)
            + '<a href="#news">News and calendar</a></nav>']
    body = "\n".join(head) + "\n" + "\n".join(_study_html(s, charts) for s in studies)
    body += ('<section class="card" id="news"><div class="eyebrow">News</div><h2>News and calendar</h2>'
             + news_html(news["tickers"].get(tk, []), f"{tk} headlines (Yahoo Finance)", "No saved headlines yet.")
             + news_html(news["fed"], "Federal Reserve press releases", "No saved Fed releases yet.", 6)
             + "<h3>Upcoming scheduled events</h3>" + calendar_html(cal) + "</section>")
    body += "\n" + _health_html(health, "Checks on this tab's data") + FOOTER
    return _page(f"{tk} | Tickers", body, charts, out_dir / f"ticker_{tk}.html")


def build_overview(snaps: dict, news: dict, cal: list[dict], health: dict, out_dir: Path) -> Path:
    rows = []
    for cat, tks in CATEGORIES:
        rows.append(f'<tr class="group"><td colspan="11"><b>{escape(cat)}</b></td></tr>')
        for tk in tks:
            s = snaps.get(tk)
            if not s:
                continue
            cells = [f'<a href="ticker_{tk}.html">{tk}</a>', f"${s['last']:,.2f}", pct(s["d1"], 2), pct(s["w1"], 1), pct(s["m1"], 1), pct(s["ytd"], 1),
                     pct(s["y1"], 1), pct(s["vol20"], 0, False), pct_dd(s["dd_now"]), f"{s['beta']:.2f}", f"{s['corr']:.2f}"]
            rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    any_date = next(iter(snaps.values()))["date"] if snaps else None
    table = ('<div class="table-wrap"><table class="compare"><caption>All tickers side by side'
             + (f" (closes on {escape(_day(any_date))})" if any_date else "") + "</caption><thead><tr>"
             + "".join(f'<th scope="col">{h}</th>' for h in ["Ticker", "Close", "1 day", "1 week", "1 month", "This year", "1 year", "Volatility (20 days)",
                                                            "Below peak", "Moves per 1% SPY", "Moves with SPY"])
             + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")
    cards = "".join(
        f'<a class="tk-card" href="ticker_{tk}.html"><b>{tk}</b><span>{escape(NAMES[tk])}</span></a>' for _, tks in CATEGORIES for tk in tks)
    latest = []
    for tk, items in news["tickers"].items():
        for i in items[:4]:
            latest.append({**i, "title": f"[{tk}] {i['title']}"})
    seen, merged = set(), []
    for i in sorted(latest, key=lambda x: x.get("time", ""), reverse=True):
        if i["url"] not in seen:
            seen.add(i["url"])
            merged.append(i)
    sm = health["summary"]
    body = "\n".join([
        hub_nav("tickers"), subnav("all"), "<header>", '<div class="eyebrow">Index research &middot; tickers</div>',
        "<h1>Every index ETF: its own page with stats, charts, order flow and news</h1>",
        f'<p class="sub">Built {datetime.now():%b %d, %Y %I:%M %p}</p>', "</header>",
        '<section class="card"><h2>Pick a ticker</h2><p class="question">Each page has the Indexes tab\'s studies for that ticker, plus its charts, '
        "daily order-flow stand-ins, related Kalshi perps, and its news. The Indexes tab stays the summary.</p>"
        f'<div class="tk-cards">{cards}</div>'
        f'<p class="muted small">Data check: <b>{sm["warn"]}</b> warnings, <b>{sm["note"]}</b> notes, {sm["ok"]} OK. <a href="#health">See it</a>.</p></section>',
        f'<section class="card">{table}</section>',
        '<section class="card" id="news"><div class="eyebrow">News</div><h2>Latest headlines and calendar</h2>'
        + news_html(merged, "Latest across all tickers (Yahoo Finance)", "No saved headlines yet.", 14)
        + news_html(news["fed"], "Federal Reserve press releases", "No saved Fed releases yet.", 8)
        + "<h3>Upcoming scheduled events</h3>" + calendar_html(cal) + "</section>",
        _health_html(health, "Checks on this tab's data"), FOOTER,
    ])
    out = _page("Tickers", body, {}, out_dir / "tickers.html")
    write_hub_index(out_dir)
    return out
