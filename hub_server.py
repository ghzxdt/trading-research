"""Local dashboard server with authenticated desktop lifecycle control.

Only loopback is bound. Shutdown needs the local controller secret, and active
or uncertain writers block restart. Data, paper logs and backups are preserved.
"""
from __future__ import annotations
import argparse, hmac, json, os, secrets, subprocess, sys, threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from app_control import app_identity,build_lock_state,hidden_process_flags,utc_now
import refresh_guard
from urllib.parse import urlparse, parse_qs
from terminal_api import handle_get, start_action

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output'
WORK=ROOT/'work'
LOCK=threading.Lock()
# Append-only thesis logs the page can write to: path -> (key of the saved row in the reply, writer).
THESIS_WRITES={'/api/v1/thesis/call':('call','calls'),'/api/v1/thesis/note':('note','journal'),
               '/api/v1/thesis/idea':('idea','idea'),'/api/v1/thesis/idea/update':('idea','idea_update')}
STATE_LOCK=threading.RLock()
BUILD_STATE={'running':False,'ok':None,'message':'Ready','action':None}
SERVER_STARTED=utc_now()


def load_build_state():
    try:
        saved=json.loads((WORK/'build_status.json').read_text(encoding='utf-8'))
        if not isinstance(saved,dict):return
        if saved.get('running'):saved.update(running=False,ok=False,message='Previous server stopped during a refresh. Check the build lock and refresh log.')
        with STATE_LOCK:BUILD_STATE.update(saved)
    except (OSError,ValueError):pass


def update_build_state(**values):
    with STATE_LOCK:
        BUILD_STATE.update(values)
        WORK.mkdir(parents=True,exist_ok=True)
        temp=WORK/'build_status.tmp'
        temp.write_text(json.dumps(BUILD_STATE,indent=2),encoding='utf-8');temp.replace(WORK/'build_status.json')


def control_secret():
    WORK.mkdir(parents=True,exist_ok=True);p=WORK/'controller_secret.txt'
    try:
        with p.open('x',encoding='ascii') as stream:stream.write(secrets.token_urlsafe(32))
    except FileExistsError:pass
    token=p.read_text(encoding='ascii').strip()
    if len(token)<24:raise RuntimeError('Local controller secret is invalid; server not started.')
    return token


def status_payload():
    lock=build_lock_state(ROOT)
    with STATE_LOCK:build=dict(BUILD_STATE)
    return {'ok':True,'app_id':app_identity(ROOT),'app_root':str(ROOT),'server_version':'desktop-control-v1',
            'server_pid':os.getpid(),'server_started_at':SERVER_STARTED,'busy':LOCK.locked() or lock['busy'],'build_lock':lock,'build':build}


def refresh_all(offline):
    try:
        # The request handler already applied (or was told to override) the VIX guard.
        command=[sys.executable,'-B',str(ROOT/'run_all.py')]+(['--offline'] if offline else ['--skip-vix-guard'])
        WORK.mkdir(parents=True,exist_ok=True)
        with (WORK/'last_refresh.log').open('w',encoding='utf-8') as stream:
            # Do not kill just the parent on an outer timeout while builder children write.
            result=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,creationflags=hidden_process_flags())
        update_build_state(running=False,ok=result.returncode==0,exit_code=result.returncode,finished_at=utc_now(),
                           message='Validated bundle published. Reload this page.' if result.returncode==0 else 'Build failed; previous complete output is preserved. Open the refresh log.')
    except Exception as exc:update_build_state(running=False,ok=False,message=str(exc),finished_at=utc_now())
    finally:LOCK.release()


def make_handler(port:int,downloads:Path|None,token:str|None=None):
    hosts={f'localhost:{port}',f'127.0.0.1:{port}'}
    token=control_secret() if token is None else token
    stopping=threading.Event()
    def reserve_work():
        if stopping.is_set() or not LOCK.acquire(blocking=False):return False
        # Recheck after acquiring: shutdown may have won the race between checks.
        if stopping.is_set():LOCK.release();return False
        return True
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*a,**k):super().__init__(*a,directory=str(OUT),**k)
        def log_message(self,fmt,*args):pass
        def end_headers(self):self.send_header('Cache-Control','no-store');super().end_headers()
        def _json(self,code,body):
            data=json.dumps(body).encode('utf-8');self.send_response(code)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            route=urlparse(self.path)
            if route.path.startswith('/api/v1/'):
                code,body=handle_get(ROOT,route.path,parse_qs(route.query))
                return self._json(code,body)
            if self.path.split('?')[0]=='/api/status':return self._json(200,status_payload())
            return super().do_GET()
        def do_POST(self):
            if self.headers.get('Host') not in hosts or self.headers.get('X-Hub')!='1':return self._json(403,{'ok':False,'error':'Not allowed.'})
            if stopping.is_set():return self._json(503,{'ok':False,'error':'Dashboard is stopping; retry after it restarts.'})
            if self.path in THESIS_WRITES:
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<=length<=16384:return self._json(413,{'ok':False,'error':'Request too large.'})
                    payload=json.loads(self.rfile.read(length) or b'{}')
                except (ValueError,TypeError):return self._json(400,{'ok':False,'error':'Invalid request JSON.'})
                # A build hashes data/ before and after; a write in between would make it refuse to publish.
                if build_lock_state(ROOT)['busy']:return self._json(409,{'ok':False,'error':'A build is running. Try again in a minute.'})
                try:
                    from thesis import calls,journal,ledger
                    key,write=THESIS_WRITES[self.path]
                    row={'calls':calls.append,'journal':journal.append,'idea':ledger.create,'idea_update':ledger.update}[write](ROOT,payload)
                except ValueError as exc:return self._json(400,{'ok':False,'error':str(exc)})
                return self._json(200,{'ok':True,key:row})
            if self.path.startswith('/api/v1/intraday/'):
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<=length<=32768:return self._json(413,{'ok':False,'error':'Request too large.'})
                    payload=json.loads(self.rfile.read(length) or b'{}')
                    if not isinstance(payload,dict):raise ValueError('A JSON object is required.')
                except (ValueError,TypeError):return self._json(400,{'ok':False,'error':'Invalid request JSON.'})
                if build_lock_state(ROOT)['busy'] or not reserve_work():return self._json(409,{'ok':False,'error':'An app writer is active.'})
                def finished():LOCK.release()
                try:
                    code,body=start_action(ROOT,self.path,payload,update_build_state,finished)
                except Exception as exc:
                    LOCK.release();return self._json(400,{'ok':False,'error':str(exc)})
                return self._json(code,body)
            if self.path=='/api/shutdown':
                if not hmac.compare_digest(self.headers.get('X-Local-Control',''),token):return self._json(403,{'ok':False,'error':'Local desktop authentication is required.'})
                if not reserve_work():return self._json(409,{'ok':False,'error':'A refresh/build is active or cannot be checked. Wait before restarting.'})
                try:
                    if build_lock_state(ROOT)['busy']:return self._json(409,{'ok':False,'error':'A refresh/build is active or cannot be checked. Wait before restarting.'})
                    stopping.set()
                    self._json(200,{'ok':True,'message':'Dashboard stopping. Data, logs and backups are preserved.'})
                    threading.Thread(target=self.server.shutdown,daemon=True).start()
                except Exception:stopping.clear();raise
                finally:LOCK.release()
                return
            if self.path in ('/api/refresh','/api/rebuild'):
                writer=build_lock_state(ROOT)
                if writer['exists']:return self._json(409,{'ok':False,'error':writer['reason']})
                offline=self.path=='/api/rebuild'
                # An online refresh before Cboe posts the VIX close would log the day's paper decisions as data_blocked.
                if not offline and self.headers.get('X-Allow-Data-Blocked')!='1':
                    reason=refresh_guard.blocking_reason(ROOT)
                    if reason:return self._json(409,{'ok':False,'error':reason})
                if not reserve_work():return self._json(409,{'ok':False,'error':'A build is already running or the dashboard is stopping.'})
                try:
                    update_build_state(running=True,ok=None,message='Building and validating a complete bundle...',action='offline' if offline else 'online',started_at=utc_now(),finished_at=None,exit_code=None)
                    threading.Thread(target=refresh_all,args=(offline,),daemon=True).start()
                except Exception:LOCK.release();raise
                with STATE_LOCK:build=dict(BUILD_STATE)
                return self._json(202,{'ok':True,'build':build})
            if self.path!='/api/gex/update':return self._json(404,{'ok':False,'error':'Unknown action.'})
            if build_lock_state(ROOT)['exists'] or not reserve_work():return self._json(409,{'ok':False,'error':'A build/update is already running or the dashboard is stopping.'})
            try:
                from gex import importer
                result=importer.import_latest(downloads)
                if not result['ok']:return self._json(200,result)
                run=subprocess.run([sys.executable,'-B',str(ROOT/'run_gex.py')],cwd=ROOT,capture_output=True,text=True,timeout=600,creationflags=hidden_process_flags())
                if run.returncode!=0:return self._json(200,{'ok':False,'error':'Imported file, but tab rebuild failed: '+(run.stderr or run.stdout)[-400:]})
                return self._json(200,result)
            finally:LOCK.release()
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--downloads',help='Folder containing the manually downloaded DIX CSV');args=parser.parse_args()
    load_build_state()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(args.port,Path(args.downloads) if args.downloads else None))
    print(f'Hub running at http://localhost:{args.port}',flush=True)
    try:server.serve_forever(poll_interval=.15)
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
