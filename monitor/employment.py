"""Official BLS observations with immutable source snapshots and explicit missing consensus.

First observation is not necessarily the first release. Automatic text extraction
is displayed for review, never used as a trading signal. Imported release vintages
can be point-in-time tested only when their availability timestamps are supplied.
"""
from __future__ import annotations
import hashlib, html, json, re, math
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

RELEASE_URL='https://www.bls.gov/news.release/empsit.htm'
CALENDAR_URL='https://www.bls.gov/schedule/news_release/bls.ics'


def parse_release(source):
    source=re.sub(r'<(script|style)\b[^>]*>.*?</\1>',' ',source,flags=re.I|re.S)
    text=html.unescape(re.sub('<[^>]+>',' ',source))
    text=re.sub(r'\s+',' ',text)
    title=re.search(r'Employment Situation\s*[-–—]+\s*([A-Za-z]+\s+20\d{2})',text,re.I)
    period=title.group(1) if title else None
    payroll=re.search(r'total nonfarm payroll employment\s+(.{0,180}?)\.',text,re.I)
    nfp=None
    if payroll:
        clause=payroll.group(1)
        number=re.search(r'\bby\s+([0-9,]+)|\(\s*([+\-]?[0-9,]+)\s*\)',clause)
        if number:
            nfp=float((number.group(1) or number.group(2)).replace(',',''))
            if re.search(r'declin|decreas|fell|down|lost',clause,re.I):nfp=-abs(nfp)
    unemp=re.search(r'unemployment rate.{0,110}?(\d+(?:\.\d+)?)\s*percent',text,re.I)
    # Prefer an explicit percent change, never convert a dollar change into percent.
    wage=re.search(r'average hourly earnings for all employees.{0,220}?(?:or\s+|by\s+)(\d+(?:\.\d+)?)\s*percent',text,re.I)
    return {'reference_period':period,'payroll_change':nfp,
            'unemployment_rate':float(unemp.group(1)) if unemp else None,
            'wage_change_mom_pct':float(wage.group(1)) if wage else None,
            'prior_revisions':'Review the archived release; no automatic revision attribution.',
            'status':'unreviewed automatic extraction','release_at':None,
            'vintage_warning':'Latest published page observed at retrieval; first-release vintage and exact publication time are not certified.'}


def parse_calendar(source):
    events=[]
    unfolded=re.sub(r'\r?\n[ \t]','',source)
    for block in unfolded.split('BEGIN:VEVENT')[1:]:
        fields={}
        for line in block.splitlines():
            if ':' in line:
                k,v=line.split(':',1);fields[k.split(';')[0]]=v.strip()
        summary=fields.get('SUMMARY','')
        if not re.search('Employment Situation|Consumer Price Index',summary,re.I):continue
        value=fields.get('DTSTART','')
        try:
            when=pd.to_datetime(value,format='%Y%m%dT%H%M%SZ',utc=True) if value.endswith('Z') else pd.to_datetime(value,format='%Y%m%dT%H%M%S').tz_localize('America/New_York')
        except (ValueError,TypeError):continue
        events.append({'date':str(when.tz_convert('America/New_York').date()),'release_at':when.isoformat(),
                       'event':'jobs_report' if 'Employment Situation' in summary else 'cpi','summary':summary})
    return events


def refresh(root):
    folder=root/'data/employment';folder.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone.utc).isoformat();results={}
    for name,url in [('employment',RELEASE_URL),('calendar',CALENDAR_URL)]:
        try:
            response=requests.get(url,timeout=25,headers={'User-Agent':'index-research-audit/2.0 (personal economic research)'})
            response.raise_for_status();body=response.text
            parsed=parse_release(body) if name=='employment' else parse_calendar(body)
            if name=='calendar' and not parsed:raise ValueError('No supported calendar entries parsed')
            if name=='employment' and not parsed.get('reference_period'):raise ValueError('Release period could not be extracted; retaining previous snapshot')
            digest=hashlib.sha256(body.encode()).hexdigest()
            snapshots=folder/'snapshots';snapshots.mkdir(exist_ok=True)
            artifact=snapshots/(name+'_'+digest[:20]+('.html' if name=='employment' else '.ics'))
            if not artifact.exists():artifact.write_text(body,encoding='utf-8')
            current={'observed_at':now,'url':url,'source_sha256':digest,'source_file':str(artifact.relative_to(root)),
                     'parsed':parsed,'reviewed':False}
            target=folder/(name+'.json');temp=target.with_suffix('.tmp')
            temp.write_text(json.dumps(current,indent=2),encoding='utf-8');temp.replace(target)
            results[name]={'ok':True,'observed_at':now}
        except Exception as exc:
            results[name]={'ok':False,'error':str(exc),'attempted_at':now}
    (folder/'refresh_status.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return results


def load(root):
    result={}
    for name in ('employment','calendar','refresh_status'):
        path=root/'data/employment'/(name+'.json')
        result[name]=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    vintages=root/'data/employment/releases.csv'
    expectations=root/'data/employment/expectations.csv'
    result['releases']=pd.read_csv(vintages).to_dict('records') if vintages.exists() else []
    result['expectations']=pd.read_csv(expectations).to_dict('records') if expectations.exists() else []
    return result


def validated_surprises(releases,expectations):
    """No surprise is computed from an expectation observed after publication."""
    out=[]
    for release in releases:
        for expected in expectations:
            if (release.get('metric'),release.get('reference_period'))!=(expected.get('metric'),expected.get('reference_period')):continue
            try:
                released=pd.Timestamp(release['available_at']);known=pd.Timestamp(expected['available_at'])
                if released.tzinfo is None or known.tzinfo is None or known>=released:continue
                actual,consensus=float(release['actual']),float(expected['consensus'])
                if not all(math.isfinite(x) for x in [actual,consensus]):continue
                out.append({**release,'consensus':consensus,'expectation_available_at':known.isoformat(),'surprise':actual-consensus})
            except (ValueError,TypeError,KeyError):continue
    return out
