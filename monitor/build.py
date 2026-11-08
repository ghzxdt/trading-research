"""Audit comparison pages and transparent performance experiments."""
from __future__ import annotations
import hashlib,json,os,re,subprocess,sys
from html import escape
from pathlib import Path
import numpy as np
import pandas as pd
from stage1 import report
from stage1.studies import adjust_pvalues
from validation import freshness,now_et
import crosscheck
from . import backtest,employment,paper


def fmt(x,d=2):
    return 'Unavailable' if x is None or not np.isfinite(float(x)) else f'{float(x)*100:+.{d}f}%'


def probability(x):
    return 'Unavailable' if x is None or not np.isfinite(float(x)) else f'{float(x):.4g}'


def safe(obj):
    if isinstance(obj,dict):return {str(k):safe(v) for k,v in obj.items()}
    if isinstance(obj,(list,tuple)):return [safe(v) for v in obj]
    if isinstance(obj,(pd.Timestamp,Path)):return str(obj)
    if isinstance(obj,(np.integer,)):return int(obj)
    if isinstance(obj,(np.bool_,)):return bool(obj)
    if isinstance(obj,(float,np.floating)):return float(obj) if np.isfinite(obj) else None
    return obj


def dump(path,obj):path.write_text(json.dumps(safe(obj),indent=2,allow_nan=False),encoding='utf-8')


def section(key,title,question='',tables=None,charts=None,tiles=None):
    return {'id':key,'number':1,'title':title,'question':question,'tiles':tiles or [],'findings':[],
            'tables':tables or [],'charts':charts or [],'show_tables':True}


def table(title,columns,rows):return {'title':title,'columns':columns,'rows':rows}


def page(out,filename,key,title,lead,sections,extra=''):
    charts={}
    body=report.hub_nav(key)+f'<header><div class="eyebrow">RESEARCH VALIDATION</div><h1>{escape(title)}</h1><p class="sub">{escape(lead)}</p></header>'
    body+=f'<section class="card"><p>Run {escape(os.environ.get("APP_RUN_ID","standalone"))} · observation clock {escape(now_et().isoformat())}. ETF proxies and cost scenarios are research, not actual Kalshi fills.</p>{extra}</section>'
    for n,s in enumerate(sections,1):s['number']=n;body+=report._study_html(s,charts)
    body+='<footer class="card"><p>Original code and data are preserved in backups. Forward paper results are separate from historical research. Missing data remains unavailable; no account orders are sent.</p></footer>'
    text=report.TEMPLATE.read_text(encoding='utf-8').replace('{{TITLE}}',escape(title)).replace('{{BODY}}',body).replace('{{CHART_DATA}}',json.dumps(safe(charts),separators=(',',':')).replace('</','<\\/'))
    (out/filename).write_text(text,encoding='utf-8')


def run_probe(root,out,code_root,name):
    path=out/(name+'_probe.json')
    subprocess.run([sys.executable,'-B',str(root/'monitor/probe.py'),'--code-root',str(code_root),'--data-root',str(root),'--out',str(path)],cwd=root,check=True)
    return json.loads(path.read_text(encoding='utf-8'))


def compare(root,out,old,new):
    a,b=old['metrics'],new['metrics']
    rows=[]
    for field,label in [('rally_next_mean','Big-rise next-day raw mean'),('rally_next_ex_covid','Same, excluding the disclosed 2020 window'),
                        ('high_vix_rally_next','High-VIX big-rise next-day raw mean'),('high_vix_rally_ex_covid','Same, excluding the disclosed 2020 window')]:
        rows.append([label,fmt(a.get(field),3),fmt(b.get(field),3),'Descriptive research; before costs'])
    aligned_original=a.get('SPXU_growth_all',0)/(1+a.get('SPXU_first_return',0))
    rows.append(['SPXU wealth per $1 at the common first close',f"${aligned_original:.9f}",f"${b.get('SPXU_growth_buy_hold',b.get('SPXU_growth_all',0)):.9f}",'Both normalized to the first table close; corrected curve preserves the price change across a missing intermediate observation'])
    rows.append(['Missing margin: historical long barrier hits',fmt(a.get('missing_margin_long_hit_rate')),fmt(b.get('missing_margin_long_hit_rate')),'Unavailable must not mean zero risk'])
    registry=adjust_pvalues(new['tests'])
    tests=[]
    for i,r in enumerate(registry):
        previous=old['tests'][i] if i<len(old['tests']) else {}
        label=r.get('test_id',f'Test {i+1}') if i<30 else ['Negative GEX: move size','High DIX: five-session direction','Low DIX: five-session direction'][i-30]
        tests.append([label,r.get('n',''),probability(previous.get('p')),probability(r.get('p')),probability(r.get('p_bh')),probability(r.get('p_holm'))])
    gate=[['Calendar horizons','Missing rows retain their exchange sessions','Corrected'],['Wealth curves','Valid-close endpoint wealth; paired-sample decomposition','Corrected'],
          ['Liquidation estimates','Unknown handling and side-specific inputs','Corrected; exact broker liquidation remains uncalibrated'],
          ['Event studies','Emergency actions excluded from advance calendar signals; matched size controls','Corrected'],
          ['Inference','Stable IDs, nonzero Monte Carlo p, raw/BH/Holm shown together','Exploratory; not independent proof'],
          ['Trading costs','Explicit configurable execution/funding scenarios','Scenario model; historical venue fills still needed']]
    page(out,'monitor.html','compare','Original vs corrected',
         'Frozen original reports plus same-input code comparisons. A lower historical result can be the accurate result.',
         [section('diff','Calculation differences','Both versions below use the same current cached market inputs; the old algorithms are loaded from the frozen backup.',[table('Original algorithms vs corrected algorithms',['Measure','Original','Corrected','Interpretation'],rows)]),
          section('repairs','Repair coverage',tables=[table('What changed',['Area','Behavior','Status'],gate)]),
          section('tests','Statistical support across the full test family','Probabilities are decimals: 0.05 means 5%. Small nonzero values retain precision. Unavailable matched tests lack sufficient controls. Changed null methods and controls are part of the correction.',[table('All Indexes + GEX tests',['Test','Cases','Original raw p','Corrected raw p','BH adjusted','Holm adjusted'],tests)])],
         '<p><a href="baseline/report.html">Open the frozen original Indexes report</a> · <a href="baseline/tickers.html">Original tickers</a> · <a href="baseline/leverage.html">Original leverage</a> · <a href="baseline/gex.html">Original GEX</a></p><p>Use Backtests for economic results. Use Paper monitor for decisions recorded before future entries.</p>')
    dump(out/'statistical_registry.json',registry)
    return registry


def backtests(root,out,t,costs):
    sections=[];summary=[];all_trades=[]
    for rule in backtest.STRATEGIES:
        old,oldcurve,os_=backtest.simulate(t,rule,costs,'original',False)
        oldnet,oldnetcurve,ons=backtest.simulate(t,rule,costs,'original',True)
        revised,curve,rs=backtest.simulate(t,rule,costs,'corrected',True)
        sensitivity=[]
        for name,scale in [('Half execution cost',.5),('Configured cost',1),('Double execution cost',2)]:
            c={**costs,**{k:costs[k]*scale for k in ('half_spread_bps','slippage_bps_per_side','fee_bps_per_side')}}
            _,_,r=backtest.simulate(t,rule,c,'corrected',True)
            sensitivity.append([name,fmt(r['return']),fmt(r['mean_trade'],3),fmt(r['max_drawdown'])])
        interval=backtest.bootstrap_mean_interval(revised)
        ci='Insufficient sample' if interval is None else fmt(interval[0],3)+' to '+fmt(interval[1],3)
        summary.append([rule['name'],rs['trades'],fmt(os_['return']),fmt(ons['return']),fmt(rs['return']),fmt(rs['max_drawdown']),fmt(rs['mean_trade'],3),ci])
        idx=curve.resample('W-FRI').last().dropna().index
        # Resampled labels may be after the last observed session; use actual session dates.
        positions=t.index.to_series().resample('W-FRI').last().dropna().tolist()
        spec={'id':'bt_'+rule['id'],'type':'line','format':'dollar','title':rule['name']+' — research equity',
              'subtitle':'$10,000 initial equity; 1x-or-less notional; no overlapping trades within a rule. Daily marked equity, excluding unobserved intraday excursions.',
              'x':[str(x.date()) for x in positions],
              'series':[{'name':'Original close entry, gross','values':[float(oldcurve.loc[x]) for x in positions]},
                        {'name':'Original close entry, scenario net','values':[float(oldnetcurve.loc[x]) for x in positions]},
                        {'name':'Corrected next-open entry, scenario net','values':[float(curve.loc[x]) for x in positions]}]}
        annual=backtest.summarize_periods(revised)
        sections.append(section(rule['id'],rule['name'],
            'The original close-entry series assumes an entry before the completed signal was available. Corrected entries wait for the next cash-session open. Different intervals can change results materially.',
            [table('Execution-cost stress',['Scenario','Total return','Mean trade','Max daily marked drawdown'],sensitivity),
             table('Year-by-year research diagnostics; all these historical years were inspected during development',['Year','Trades','Gross mean','Scenario net mean','Net winning trades'],[[y,n,fmt(g,3),fmt(net,3),fmt(w)] for y,n,g,net,w in annual])],[spec]))
        if not revised.empty:all_trades.append(revised)
    summary_table=table('Paired experiment scoreboard',['Frozen candidate','Trades','Original gross','Original scenario net','Corrected scenario net','Corrected drawdown','Net mean/trade','95% year-block mean interval'],summary)
    assumptions=table('Editable assumptions in monitor_config.json',['Setting','Value'],[[k,str(v)] for k,v in costs.items()])
    page(out,'backtests.html','backtests','After-cost backtests','Historical ETF-proxy experiments, not a verified live trading record.',
         [section('score','Compare economic outcomes','Rules were selected using this history. Year blocks and confidence intervals are diagnostics, not an untouched out-of-sample claim.',[summary_table,assumptions])]+sections,
         '<p>Costs are explicit assumptions: bid/ask and slippage are applied to fills, fees apply on entry/exit notional, and funding is a prorated calendar-time scenario. The model does not claim historical Kalshi quotes, exact funding events, stop fills or liquidation execution. No leverage recommendation is produced.</p><p><a href="backtest_trades.csv">Download corrected trade ledger</a> · <a href="backtest_summary.json">Download summary</a></p>')
    pd.concat(all_trades,ignore_index=True).to_csv(out/'backtest_trades.csv',index=False,float_format='%.17g') if all_trades else pd.DataFrame(columns=['strategy','signal_date','net']).to_csv(out/'backtest_trades.csv',index=False)
    dump(out/'backtest_summary.json',{'costs':costs,'rows':summary,'mode':'retrospective ETF-proxy scenario','rules':backtest.STRATEGIES})
    return summary


def paper_page(root,out,t,costs,quality_ok):
    state=paper.update(root,t,costs,quality_ok,os.environ.get('APP_RUN_ID','standalone'))
    decisions=[e for e in state['events'] if e['type']=='decision']
    outcomes={e['key']:e for e in state['events'] if e['type']=='outcome'}
    rows=[]
    for d in decisions[-120:]:
        outcome=outcomes.get(d['key'])
        rows.append([d['name'],d['signal_date'],d['recorded_at'],'Long' if d['side']==1 else 'Short' if d['side']==-1 else 'No edge',d['entry_at'],d['state'],fmt(outcome.get('net'),3) if outcome else 'Pending'])
    scored=[(d,outcomes[d['key']]) for d in decisions if d['key'] in outcomes and d['signal'] and d['state']=='recorded_before_entry']
    scores=[]
    for rule in backtest.STRATEGIES:
        r=[o['net'] for d,o in scored if d['strategy']==rule['id']]
        scores.append([rule['name'],len(r),fmt(np.mean(r),3) if r else 'No settled trades',fmt(np.prod(1+np.array(r))-1) if r else 'Pending'])
    page(out,'paper.html','paper','Forward paper monitor','Only decisions recorded before their hypothetical entry can enter the forward scoreboard.',
         [section('paper_score','Forward scoreboard','Paper fills are next-open ETF-proxy scenarios. Each rule maintains a nonoverlapping research position; rules are scored separately.',[table('No retrospective backfilling',['Candidate','Settled signaled trades','Net mean','Compounded scenario return'],scores)]),
          section('paper_log','Immutable decision log','Hash chain is verified on every read. Rebuilds preserve prior decisions; late records and incomplete outcomes are excluded.',[table('Recent decisions',['Rule','Signal date','Recorded UTC','Decision','Planned entry','Eligibility','Outcome net'],rows or [['No records yet','—','—','—','—','Offline builds do not create forward observations','—']])])],
         '<p>Offline/replay mode: '+str(state['replay'])+'. Log chain verified: '+str(state['chain_verified'])+'. Existing experiment cost configuration changed: '+str(state['config_changed'])+'.</p><p>The first online refresh locks the rules and cost assumptions. A changed configuration does not rewrite that experiment. No settled sample means no evidence of forward profitability.</p>')
    dump(out/'paper_state.json',state)
    return state


def quality_page(root,out,t,registry):
    fresh=freshness(t.index[-1]);vixdate=t['vix'].last_valid_index();vf=freshness(vixdate)
    checks=json.loads((out/'validation_report.json').read_text(encoding='utf-8'))
    rows=[['Equity observations',fresh['last'],'PASS' if fresh['ok'] else 'BLOCKED',fresh['reason']],
          ['VIX observations',vf['last'],'PASS' if vf['ok'] else 'BLOCKED',vf['reason']],
          ['Rebuild/arithmetic checks',str(checks.get('passed')),'PASS' if checks.get('passed') else 'BLOCKED','Current transformation checks; not independent vendor certification'],
          ['Liquidation calibration','Unknown','SIZING BLOCKED','Side-specific proxy model is not reconciled against broker-displayed liquidation prices'],
          ['Independent vendor reconciliation','Partial','UNVERIFIED','SPY and QQQ daily returns are checked against FRED (next row); opens, IWM, DIA, RSP and the leveraged ETFs are not'],
          ['Historical executable venue costs','Not available','SCENARIO ONLY','Backtests expose assumptions and do not label them actual fills']]
    # Second-source price check: display only, so the gate returned below is unchanged.
    cross=crosscheck.compare(t,crosscheck.load(root));dump(out/'price_crosscheck.json',cross);rows.insert(5,crosscheck.quality_row(cross))
    manifests=[]
    for p in out.glob('manifest_*.json'):
        data=json.loads(p.read_text(encoding='utf-8'));manifests.append([data.get('component'),data.get('run_id'),data.get('as_of')])
    chart_count=0;errors=[]
    for p in out.glob('*.html'):
        m=re.search(r'<script type="application/json" id="chart-data">(.*?)</script>',p.read_text(encoding='utf-8'),re.S)
        if not m:continue
        for key,spec in json.loads(m.group(1)).items():
            chart_count+=1;x=spec.get('x',spec.get('categories',[]))
            if any(len(s['values'])!=len(x) for s in spec['series']):errors.append(p.name+':'+key)
    rows.append(['Chart array checks',str(chart_count),'PASS' if not errors else 'BLOCKED',', '.join(errors) or 'Dates/series lengths checked; complete bundle is checked again before publication'])
    page(out,'quality.html','quality','Data quality & provenance','Unknown inputs remain visible. Structural integrity, freshness, calibration and economic evidence are separate checks.',
         [section('quality','Decision gates',tables=[table('Current readiness',['Check','Observed','State','Meaning'],rows)]),
          section('manifest','One consistent build',tables=[table('Component provenance',['Component','Run ID','Observation clock'],manifests)])],
         '<p><a href="validation_report.json">Validation results</a> · <a href="build_manifest.json">Full source/input/output hash manifest</a> · <a href="statistical_registry.json">Raw/BH/Holm test registry</a></p>')
    return bool(fresh['ok'] and vf['ok'] and checks.get('passed') and not errors),rows


def jobs_page(root,out,t):
    data=employment.load(root);ob=data['employment'];cal=data['calendar'];status=data['refresh_status']
    parsed=ob['parsed'] if ob else {}
    latest=[['Reference period',parsed.get('reference_period') or 'Not collected'],['Payroll change',parsed.get('payroll_change')],
            ['Unemployment rate (%)',parsed.get('unemployment_rate')],['Wage month/month (%)',parsed.get('wage_change_mom_pct')],
            ['Observed at',ob.get('observed_at') if ob else 'Not collected'],['Extraction status',parsed.get('status','Unavailable')],
            ['First-release vintage',parsed.get('vintage_warning','No vintage has been archived yet')]]
    events=pd.read_csv(root/'data/events/events.csv')
    future=events[(events['date']>=str(now_et().date())) & events['event'].isin(['jobs_report','cpi','fed_decision'])].head(15)
    official={(e['event'],e['date']) for e in cal['parsed']} if cal else set()
    rows=[[r['date'],r['event'],r.get('time_et',''),('Matches fetched BLS calendar' if (r['event'],r['date']) in official else 'Not independently revalidated' if r['event']!='fed_decision' else 'Fed calendar; not covered by BLS ICS')] for _,r in future.iterrows()]
    surprises=employment.validated_surprises(data['releases'],data['expectations'])
    attempts=[[name,'OK' if result.get('ok') else 'Unavailable',result.get('observed_at',result.get('attempted_at','')),result.get('error','Source archived; extraction awaits review')] for name,result in (status or {}).items()]
    page(out,'jobs.html','jobs','Jobs & macro monitor','Calendar risk plus official-release observations. Missing expectations and revisions are never inferred.',
         [section('release','Latest observed BLS release','Automatic extraction is displayed for review and is not promoted to a directional signal.',[table('Official page snapshot',['Field','Value'],[[k,'Unavailable' if v is None else str(v)] for k,v in latest]),table('Source retrieval status',['Source','State','Timestamp','Detail'],attempts or [['No online attempt yet','Unavailable','—','Use online refresh or provide timestamped release inputs.']])]),
          section('calendar','Upcoming releases','All displayed release times are Eastern. Online refresh checks BLS jobs/CPI schedules against the static calendar.',[table('Calendar reconciliation',['Date','Release','ET time','Verification'],rows)]),
          section('surprises','Timestamped surprises','Consensus must have been available strictly before release availability. No consensus provider or numeric expectation is invented.',[table('Validated imported vintages',['Period','Metric','Actual','Consensus','Surprise'],[[r.get('reference_period'),r.get('metric'),r.get('actual'),r.get('consensus'),r.get('surprise')] for r in surprises] or [['No valid point-in-time inputs yet','—','—','—','—']])])],
         '<p><a href="https://www.bls.gov/news.release/empsit.htm">Official Employment Situation</a> · <a href="https://www.bls.gov/schedule/news_release/empsit.htm">Official jobs schedule</a></p><p>Online refresh archives the official release and calendar source. Consensus and historical initial/revised releases require timestamped source data; see DATA_INPUTS.md. Weekly claims/JOLTS/ADP are not silently treated as covered.</p>')
    dump(out/'employment_status.json',{'release_observed':ob.get('observed_at') if ob else None,'calendar_observed':cal.get('observed_at') if cal else None,'refresh':status,'valid_surprises':len(surprises)})


def build(root,out,refresh_jobs=False):
    out.mkdir(parents=True,exist_ok=True)
    if refresh_jobs:employment.refresh(root);crosscheck.refresh(root)
    config=root/'monitor_config.json'
    costs=backtest.validate_costs(json.loads(config.read_text(encoding='utf-8')) if config.exists() else {})
    baseline=json.loads((root/'baseline_manifest.json').read_text(encoding='utf-8'))
    code=root/'backups'/baseline['snapshot_name']
    # Verify the baseline code used for the experiment has not been edited.
    for rel,meta in baseline['files'].items():
        p=code/rel
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest()!=meta['sha256']:raise ValueError('Frozen baseline verification failed: '+rel)
    old=run_probe(root,out,code,'original');new=run_probe(root,out,root,'corrected')
    registry=compare(root,out,old,new)
    t=pd.read_csv(out/'daily_table.csv',index_col='date',parse_dates=True)
    results=backtests(root,out,t,costs)
    quality_ok,quality=quality_page(root,out,t,registry)
    ps=paper_page(root,out,t,costs,quality_ok)
    jobs_page(root,out,t)
    dump(out/'monitor_status.json',{'run_id':os.environ.get('APP_RUN_ID','standalone'),'as_of':str(t.index[-1].date()),
         'baseline_verified':True,'structural_and_freshness_ok':quality_ok,'sizing_allowed':False,
         'sizing_block':'Broker liquidation model uncalibrated; strategy expectancy not forward validated',
         'test_count':len(registry),'paper_events':len(ps['events']),'costs_are_scenarios':True,'app_version':'audit-repair-v1'})
    return out/'monitor.html'
