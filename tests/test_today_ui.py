"""Today rendering must preserve unknowns, escape source text, and remain read-only."""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from today.build import TEMPLATE, build, embedded_json, json_safe

SCRATCH = Path(__file__).resolve().parents[1] / "work" / "today_ui_tests"
SCRATCH.mkdir(parents=True, exist_ok=True)

def strict_loads(raw):
    def reject(value):
        raise AssertionError("Non-JSON numeric literal: " + value)
    return json.loads(raw, parse_constant=reject)


class TodayRenderingTests(unittest.TestCase):
    def render(self, state):
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        path = build(root, root / "output", state=state)
        return root, path.read_text(encoding="utf-8")

    def test_untrusted_news_cannot_close_embedded_json_or_create_markup(self):
        malicious = '</script><img src=x onerror="alert(1)"><script>'
        state = {"symbol": malicious, "as_of": "2026-11-09T10:00:00-05:00",
                 "news": [{"title": malicious, "url": "javascript:alert(1)"}]}
        root, html = self.render(state)
        script = re.search(r'<script type="application/json" id="today-state">(.*?)</script>',
                           html, re.S).group(1)
        self.assertNotIn("<", script)
        self.assertNotIn(malicious, html)
        self.assertEqual(strict_loads(script), state)
        self.assertEqual(strict_loads((root / "output/today_state.json").read_text(encoding="utf-8")), state)
        self.assertIn("u.protocol", html)
        self.assertIn("noopener noreferrer", html)

    def test_unknown_and_nonfinite_inputs_never_become_returns_or_recommendations(self):
        state = {"symbol": "SPY", "as_of": None,
                 "context": {"last_price": float("nan"), "change_pct": float("inf")},
                 "thesis": {"direction": "flat", "status": "insufficient_evidence"},
                 "evidence": {"n_trades": None, "net_expectancy": None},
                 "expressions": {"options": {"status": "unavailable"}}}
        original = copy.deepcopy(state)
        root, html = self.render(state)
        saved = strict_loads((root / "output/today_state.json").read_text(encoding="utf-8"))
        self.assertIsNone(saved["context"]["last_price"])
        self.assertIsNone(saved["context"]["change_pct"])
        self.assertIsNone(saved["evidence"]["net_expectancy"])
        self.assertEqual(saved["thesis"]["direction"], "flat")
        self.assertNotIn("probability", saved)
        self.assertEqual(state["thesis"], original["thesis"])
        self.assertIn("Waiting for evidence", html)
        self.assertIn("Sizing is unavailable", html)

    def test_build_does_not_touch_paper_log_or_collect_data(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            root = Path(folder)
            log = root / "data/monitor/paper_events.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text("immutable fixture\n", encoding="utf-8")
            lock = log.with_name("experiment_lock.json")
            lock.write_text('{"version":"frozen-fixture"}', encoding="utf-8")
            before = {p.name: p.read_bytes() for p in (log, lock)}
            with patch.dict(os.environ, {"APP_RUN_ID": "fixture-run"}):
                build(root, root / "output", {"symbol": "QQQ", "as_of": None})
            self.assertEqual(before, {p.name: p.read_bytes() for p in (log, lock)})
            manifest = strict_loads((root / "output/manifest_today.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["readonly_render"])
            self.assertEqual(manifest["run_id"], "fixture-run")
            self.assertEqual(manifest["component"], "today")

    def test_missing_state_uses_readonly_service_and_build_clock(self):
        calls = []
        module = types.ModuleType("terminal_state")
        def producer(root, symbol, as_of):
            calls.append((root, symbol, as_of))
            return {"symbol": symbol, "as_of": as_of, "schema_version": "1.0"}
        module.build_state = producer
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            root = Path(folder)
            with patch.dict(sys.modules, {"terminal_state": module}), patch.dict(os.environ, {"APP_AS_OF": "2026-11-09T10:00:00-05:00"}):
                build(root, root / "output")
            self.assertEqual(calls, [(root, "SPY", "2026-11-09T10:00:00-05:00")])

    def test_template_tokens_in_source_text_are_not_replaced(self):
        state = {"symbol": "SPY", "news": [{"title": "Literal {{SYMBOL}} & {{AS_OF}}"}]}
        root, _ = self.render(state)
        saved = strict_loads((root / "output/today_state.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, state)
        html = (root / "output/today.html").read_text(encoding="utf-8")
        script = re.search(r'<script type="application/json" id="today-state">(.*?)</script>', html, re.S).group(1)
        self.assertEqual(strict_loads(script), state)

    def test_state_must_be_an_object(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            with self.assertRaises(ValueError):
                build(Path(folder), Path(folder) / "output", state=[])

    def test_template_uses_safe_dom_and_has_accessible_empty_states(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        for unsafe in (".innerHTML", ".outerHTML", "document.write(", "eval("):
            self.assertNotIn(unsafe, source)
        for required in ('aria-live="polite"', 'role="tablist"', 'aria-controls="expression-body"',
                         'id="data-capability"', "No saved snapshot exists for", "first_seen_at"):
            self.assertIn(required, source)
        self.assertIn("state.universe", source)
        self.assertNotIn("cdn.jsdelivr", source)

    @unittest.skipUnless(shutil.which("node"), "Node is optional; browser script syntax check unavailable")
    def test_browser_javascript_parses(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        script = re.findall(r"<script>(.*?)</script>", source, re.S)[-1]
        result = subprocess.run([shutil.which("node"), "--check", "-"], input=script,
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is optional; DOM runtime check unavailable")
    def test_workspace_renders_bounded_research_readable_options_and_explicit_actions(self):
        """Exercise the actual browser script, including GET versus explicit POST."""
        source = TEMPLATE.read_text(encoding="utf-8")
        script = re.findall(r"<script>(.*?)</script>", source, re.S)[-1]
        state = {
            "symbol": "SOXL", "as_of": "2026-11-09T15:00:00Z", "universe": ["SOXL"],
            "instruments": [{"symbol": "SOXL", "exposure_group": "Semiconductors", "configured_leverage": 3}],
            "context": {"last_price": 25.12},
            "chart": {"mode": "intraday", "candles": [
                {"time": int(datetime(2026, 11, 6, 15, 0, tzinfo=timezone.utc).timestamp()) + i * 60,
                 "interval_seconds": 60, "open": 25, "high": 26, "low": 24,
                 "close": 25.1 + i * .01, "volume": 1000} for i in range(3)],
                "extended_candles": [{"time": int(datetime(2026, 11, 6, 21, 10, tzinfo=timezone.utc).timestamp()),
                                      "interval_seconds": 60, "open": 26, "high": 27, "low": 25,
                                      "close": 26.1, "volume": 1000}],
                "levels": [], "options_levels": []},
            "news": [
                {"title": "in-range fixture headline", "first_seen_at": "2026-11-06T15:01:10Z", "published_at": "2026-11-05T10:00:00Z"},
                {"title": "outside archive fixture headline", "first_seen_at": "2026-11-07T15:01:10Z", "published_at": "2026-11-06T15:01:10Z"}],
            "research": {
                "study": {"id": "fixture-baseline", "evidence_status": "historical_scenario"},
                "config": {"assume_bar_close_availability": True},
                "metrics": {"trades": 200, "complete_sessions": 201, "mean_trade_return": .001},
                "trades": [{"session": "session-" + str(i), "side": 1, "net_return": .001,
                            "entry_at": "2026-11-09T15:00:00Z", "exit_at": "2026-11-09T15:05:00Z",
                            "exit_reason": "target"} for i in range(200)],
                "session_returns": [{"session": str(i), "net_return": .001} for i in range(2000)],
            },
            "expressions": {"options": {
                "status": "candidate", "debit": 91, "max_loss": 91, "comparison_quantity": 1,
                "contract": {"contract_id": "FIXTURE_CALL", "right": "C", "strike": 25,
                             "expiry": "2026-11-13", "bid": .85, "ask": .90, "multiplier": 100},
                "reasons": ["Risk budget has not been configured."]}},
            "options": {"status": "observed_context", "iv_context": [
                {"expiry": "2026-11-13", "near_spot_iv_median": .6, "method": "Fixture pricing context"}],
                "levels": [{"expiry": "2026-11-13", "right": "C", "price": 25, "open_interest": 123,
                            "source": "Fixture", "knowledge_time": "2026-11-09T14:00:00Z"}]},
        }
        harness = r'''
const vm=require('node:vm');
const nodes=new Map();
class El{
 constructor(tag){this.tag=tag;this.children=[];this.style={};this.attrs={};this.events={};this.checked=false;this.disabled=false;this._text='';}
 get textContent(){return this._text+this.children.map(x=>typeof x==='string'?x:x.textContent).join(' ');}
 set textContent(value){this._text=String(value);this.children=[];}
 append(...values){this.children.push(...values);}
 replaceChildren(...values){this._text='';this.children=values;}
 setAttribute(key,value){this.attrs[key]=String(value);}
 addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
 focus(){}
}
const document={getElementById(id){if(!nodes.has(id))nodes.set(id,new El('div'));return nodes.get(id);},createElement:tag=>new El(tag),createElementNS:(ns,tag)=>new El(tag)};
document.getElementById('today-state').textContent=JSON.stringify(payload.state);
document.getElementById('show-vwap').checked=true;document.getElementById('show-levels').checked=true;document.getElementById('show-news').checked=true;
const requests=[];
let pending=null,operations=0,prematureReads=0;
const fetch=async(url,options={})=>{
 const request={url,method:options.method||'GET',body:options.body?JSON.parse(options.body):null};requests.push(request);
 if(options.method==='POST'){
  pending={action:'intraday_'+url.split('/').at(-1),started_at:'fixture-operation-'+(++operations),polls:0};
  return{ok:true,status:202,json:async()=>({ok:true,running:true,action:url.split('/').at(-1),started_at:pending.started_at})};
 }
 if(url==='/api/status'){
  pending.polls++;const running=pending.polls<2;request.response_running=running;
  return{ok:true,status:200,json:async()=>({ok:true,build:{...pending,running,ok:running?null:true,message:running?'Working':pending.action==='intraday_paper'?'Research observation: abstain.':'Finished fixture operation',terminal_result:{recorded:true,state:'abstain'}}})};
 }
 if(pending&&pending.polls<2){prematureReads++;throw new Error('Premature state reload');}
 return{ok:true,status:200,json:async()=>payload.state};
};
const context={document,location:{protocol:'http:',href:'http://localhost:8766/today.html',origin:'http://localhost:8766'},fetch,URL,Blob,setTimeout:fn=>setImmediate(fn),console};
vm.runInNewContext(payload.script,context);
setImmediate(async()=>{
 try{
  const readRequests=requests.slice(),researchText=document.getElementById('research-body').textContent,chartText=document.getElementById('chart').textContent,newsNote=document.getElementById('chart-news-note').textContent,extendedDefault=document.getElementById('show-extended').checked;
  document.getElementById('show-extended').checked=true;document.getElementById('show-extended').events.change[0]();
  const extendedPrice=document.getElementById('last-price').textContent,extendedMode=document.getElementById('chart-mode').textContent;
  document.getElementById('show-extended').checked=false;document.getElementById('show-extended').events.change[0]();
  document.getElementById('tab-options').events.click[0]();
  const optionsText=document.getElementById('expression-body').textContent;
  await document.getElementById('run-research').events.click[0]();
  document.getElementById('assume-archive-timing').checked=true;
  await document.getElementById('run-research').events.click[0]();
  await document.getElementById('record-observation').events.click[0]();
  process.stdout.write(JSON.stringify({readRequests,requests,prematureReads,researchText,optionsText,chartText,newsNote,extendedDefault,extendedPrice,extendedMode,watchlist:document.getElementById('watchlist').textContent,oiOverlay:document.getElementById('show-options-levels').checked,journalAction:document.getElementById('journal-action-status').textContent}));
 }catch(error){console.error(error);process.exitCode=1;}
});
'''
        code = "const payload=" + json.dumps({"state": state, "script": script}) + ";\n" + harness
        result = subprocess.run([shutil.which("node"), "-"], input=code, capture_output=True,
                                text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = strict_loads(result.stdout)
        self.assertLess(len(rendered["researchText"]), 6500)
        self.assertIn("session-199", rendered["researchText"])
        self.assertNotIn("session-0", rendered["researchText"])
        self.assertIn("historical scenario", rendered["researchText"])
        self.assertIn("FIXTURE_CALL", rendered["optionsText"])
        self.assertIn("$0.85 / $0.90", rendered["optionsText"])
        self.assertIn("60.0%", rendered["optionsText"])
        self.assertIn("Risk budget has not been configured.", rendered["optionsText"])
        self.assertNotIn('"contract_id":', rendered["optionsText"])
        self.assertIn("Semiconductors", rendered["watchlist"])
        self.assertFalse(rendered["oiOverlay"])
        self.assertFalse(rendered["extendedDefault"])
        self.assertEqual(rendered["extendedPrice"], "$26.10")
        self.assertEqual(rendered["extendedMode"], "Intraday + extended")
        self.assertIn("in-range fixture headline", rendered["chartText"])
        self.assertNotIn("outside archive fixture headline", rendered["chartText"])
        self.assertIn("1 first-seen headlines", rendered["newsNote"])
        self.assertTrue(all(request["method"] == "GET" for request in rendered["readRequests"]))
        posts = [request for request in rendered["requests"] if request["method"] == "POST"]
        self.assertEqual([request["url"] for request in posts], [
            "/api/v1/intraday/research", "/api/v1/intraday/research", "/api/v1/intraday/paper"])
        self.assertFalse(posts[0]["body"]["assume_bar_close_availability"])
        self.assertTrue(posts[1]["body"]["assume_bar_close_availability"])
        self.assertEqual(rendered["prematureReads"], 0)
        self.assertEqual([request["response_running"] for request in rendered["requests"]
                          if request["url"] == "/api/status"], [True, False, True, False, True, False])
        self.assertIn("abstain", rendered["journalAction"])


class JsonSafetyTests(unittest.TestCase):
    def test_date_boolean_and_unicode_roundtrip(self):
        moment = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
        value = {"when": moment, "valid": True, "zero": 0, "missing": float("-inf"),
                 "label": "S&P \u2028 Nasdaq > Russell"}
        safe = strict_loads(embedded_json(value))
        self.assertIs(safe["valid"], True)
        self.assertEqual(safe["zero"], 0)
        self.assertIsNone(safe["missing"])
        self.assertEqual(safe["when"], moment.isoformat())
        self.assertEqual(safe["label"], value["label"])
        self.assertNotIn("\u2028", embedded_json(value))


if __name__ == "__main__":
    unittest.main()
