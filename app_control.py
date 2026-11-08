"""Desktop lifecycle control for this app only; never terminate arbitrary PIDs."""
from __future__ import annotations
import ctypes, hashlib, json, os, socket, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ControlError(RuntimeError):
    """A lifecycle refusal that can be shown directly in the desktop panel."""


def app_identity(root):
    return hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:24]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def hidden_process_flags():
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0


def process_alive(pid):
    """False only when a process is definitely gone; access denied stays unknown."""
    if not isinstance(pid,int) or pid <= 0 or pid > 0xFFFFFFFF:
        return None
    if os.name != 'nt':
        try: os.kill(pid,0); return True
        except ProcessLookupError: return False
        except OSError: return None
    from ctypes import wintypes as w
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];k.WaitForSingleObject.restype=w.DWORD
    k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.OpenProcess(0x100000,False,pid)  # SYNCHRONIZE, never termination rights
    if not handle: return False if ctypes.get_last_error()==87 else None
    try:
        result=k.WaitForSingleObject(handle,0)
        return False if result==0 else True if result==258 else None
    finally:k.CloseHandle(handle)


def active_descendants(pid):
    """Find builder children that survived a parent. None means unsafe to clear."""
    parents={}
    if os.name=='nt':
        from ctypes import wintypes as w
        class Entry(ctypes.Structure):
            _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ProcessID',w.DWORD),
                      ('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',w.DWORD),('cntThreads',w.DWORD),
                      ('th32ParentProcessID',w.DWORD),('pcPriClassBase',w.LONG),('dwFlags',w.DWORD),('szExeFile',w.WCHAR*260)]
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
        k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
        k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.CloseHandle.argtypes=[w.HANDLE]
        handle=k.CreateToolhelp32Snapshot(2,0)
        if handle==ctypes.c_void_p(-1).value:return None
        e=Entry();e.dwSize=ctypes.sizeof(e)
        try:
            if not k.Process32FirstW(handle,ctypes.byref(e)):return None
            while True:
                parents[int(e.th32ProcessID)]=int(e.th32ParentProcessID)
                if not k.Process32NextW(handle,ctypes.byref(e)):break
            if ctypes.get_last_error() not in (0,18):return None
        finally:k.CloseHandle(handle)
    else:
        try:
            text=subprocess.check_output(['ps','-eo','pid=,ppid='],text=True,timeout=3)
            parents={int(a):int(b) for a,b in (line.split() for line in text.splitlines() if line.strip())}
        except (OSError,ValueError,subprocess.SubprocessError):return None
    found={pid}
    while True:
        new={child for child,parent in parents.items() if parent in found}
        if new.issubset(found):break
        found.update(new)
    return sorted(found-{pid})


def build_lock_state(root):
    p=Path(root)/'.build.lock'
    if not p.exists():return {'exists':False,'busy':False,'stale':False,'pid':None,'reason':'No build lock.'}
    try:
        pid=int(p.read_text(encoding='utf-8').strip())
        if pid<=0:raise ValueError('Invalid PID')
    except (OSError,ValueError):return {'exists':True,'busy':True,'stale':False,'pid':None,'reason':'Build lock is malformed or unreadable; automatic repair is unsafe.'}
    alive=process_alive(pid)
    if alive is not False:
        return {'exists':True,'busy':True,'stale':False,'pid':pid,'reason':'A build is still running.' if alive else 'Build process cannot be checked; preserving its lock.'}
    children=active_descendants(pid)
    if children is None or children:
        return {'exists':True,'busy':True,'stale':False,'pid':pid,'active_descendants':children,'reason':'The builder exited, but children are active or cannot be checked. Preserving the lock.'}
    return {'exists':True,'busy':False,'stale':True,'pid':pid,'reason':'Abandoned build lock can be repaired; no active owner or descendants remain.'}


class Controller:
    def __init__(self,root,port=8766):
        self.root=Path(root).resolve();self.port=int(port)
        if not 0<self.port<65536:raise ValueError('Invalid port')
        self.app_id=app_identity(self.root);self.work=self.root/'work'
        self.base_url=f'http://127.0.0.1:{self.port}'
        self.dashboard_url=f'http://localhost:{self.port}/monitor.html'

    def _request(self,route,*,method='GET',headers=None,timeout=1.2):
        req=Request(self.base_url+route,data=b'{}' if method=='POST' else None,method=method,headers={'X-Hub':'1',**(headers or {})})
        try:
            with urlopen(req,timeout=timeout) as response:return json.loads(response.read(65536).decode())
        except HTTPError as exc:
            try:message=json.loads(exc.read(65536).decode()).get('error',str(exc))
            except (ValueError,UnicodeError):message=str(exc)
            raise ControlError(message) from exc

    def _listening(self):
        try:
            with socket.create_connection(('127.0.0.1',self.port),timeout=.35):return True
        except OSError:return False

    def _saved_build(self):
        try:
            build=json.loads((self.work/'build_status.json').read_text(encoding='utf-8'))
            if build.get('running'):build={**build,'running':False,'ok':False,'message':'Previous server stopped during a refresh. Check logs and build lock.'}
            return build
        except (OSError,ValueError,AttributeError):return {'running':False,'ok':None,'message':'No completed refresh recorded.'}

    def status(self):
        lock=build_lock_state(self.root)
        try:
            raw=self._request('/api/status')
            if not isinstance(raw,dict):raise ValueError('Unknown status response')
            own=raw.get('app_id')==self.app_id
            return {**raw,'running':True,'identity_ok':own,'busy':bool(raw.get('busy')) or lock['busy'],'build_lock':lock,
                    'message':(raw.get('build',{}).get('message') or 'Dashboard running.') if own else 'This port belongs to an older dashboard or another service. It will not be stopped automatically.'}
        except (URLError,OSError,ValueError,ControlError):
            occupied=self._listening()
            return {'running':occupied,'identity_ok':False,'busy':lock['busy'],'build_lock':lock,'build':self._saved_build(),
                    'message':'Localhost port is occupied but its app identity cannot be verified.' if occupied else lock['reason'] if lock['exists'] else 'Dashboard stopped.'}

    def _python(self):
        p=self.root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not p.is_file():raise ControlError('The local Python runtime is missing. Restore it before starting the app.')
        return p

    def start(self):
        status=self.status()
        if status['running']:
            if not status['identity_ok']:raise ControlError(status['message'])
            return status
        if not (self.root/'hub_server.py').is_file():raise ControlError('hub_server.py is missing from this app folder.')
        self.work.mkdir(parents=True,exist_ok=True)
        log=self.work/'server.log'
        with log.open('a',encoding='utf-8') as stream:
            stream.write(f'\n[{utc_now()}] Starting desktop-controlled dashboard\n');stream.flush()
            child=subprocess.Popen([str(self._python()),'-B',str(self.root/'hub_server.py'),'--port',str(self.port)],cwd=self.root,stdin=subprocess.DEVNULL,
                                   stdout=stream,stderr=subprocess.STDOUT,creationflags=hidden_process_flags(),close_fds=True)
        (self.work/'server_launch.json').write_text(json.dumps({'pid':child.pid,'app_id':self.app_id,'started_at':utc_now(),'port':self.port}),encoding='utf-8')
        until=time.monotonic()+8
        while time.monotonic()<until:
            status=self.status()
            if status['running'] and status['identity_ok']:return status
            if child.poll() is not None:raise ControlError('Dashboard startup failed. '+self._tail(log,1200))
            time.sleep(.12)
        raise ControlError('The server did not become ready within eight seconds. It was not killed; inspect the server log before retrying.')

    def stop(self):
        status=self.status()
        if not status['running']:return status
        if not status['identity_ok']:raise ControlError(status['message'])
        if status['busy']:raise ControlError('A refresh/build is active or cannot be checked. Wait before stopping or restarting; data and logs will be preserved.')
        try:token=(self.work/'controller_secret.txt').read_text(encoding='ascii').strip()
        except OSError as exc:raise ControlError('Local control secret is missing. The server was not stopped.') from exc
        self._request('/api/shutdown',method='POST',headers={'X-Local-Control':token})
        until=time.monotonic()+6
        while time.monotonic()<until:
            if not self._listening():return self.status()
            time.sleep(.1)
        raise ControlError('Shutdown was requested, but the port is still in use. No process was forcibly terminated.')

    def restart(self):
        self.stop();self.recover_stale_lock();return self.start()

    def refresh(self,offline=False,allow_data_blocked=False):
        status=self.start()
        if status['busy']:raise ControlError('A refresh/build is already active.')
        if status['build_lock']['stale']:self.recover_stale_lock()
        # Before an online refresh the server checks Cboe's VIX file (refresh_guard), so give it time to answer.
        if offline:result=self._request('/api/rebuild',method='POST')
        else:result=self._request('/api/refresh',method='POST',headers={'X-Allow-Data-Blocked':'1'} if allow_data_blocked else None,timeout=60)
        if not result.get('ok'):raise ControlError(result.get('error','Refresh could not start.'))
        return self.status()

    def recover_stale_lock(self):
        state=build_lock_state(self.root)
        if not state['exists']:return {'ok':True,'recovered':False,'message':'No abandoned build lock to repair.'}
        if not state['stale'] or state['busy']:raise ControlError(state['reason'])
        status=self.status()
        if status['running'] and (not status['identity_ok'] or status['busy']):raise ControlError('A server/build may still be active. Lock was not changed.')
        p=self.root/'.build.lock'
        if p.read_text(encoding='utf-8').strip()!=str(state['pid']):raise ControlError('Build lock changed during inspection. Retry after checking status.')
        if process_alive(state['pid']) is not False or active_descendants(state['pid'])!=[]:raise ControlError('Process state changed; lock was preserved.')
        self.work.mkdir(parents=True,exist_ok=True)
        saved=self.work/('recovered_build_lock_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.txt')
        p.replace(saved)
        return {'ok':True,'recovered':True,'message':'Repaired the abandoned lock. Data, reports, paper logs and backups are unchanged.','saved_lock':str(saved)}

    @staticmethod
    def _tail(path,limit):
        try:
            with Path(path).open('rb') as stream:
                stream.seek(0,2);stream.seek(max(0,stream.tell()-limit));return stream.read(limit).decode('utf-8',errors='replace')
        except OSError:return 'No log has been written yet.'

    def last_log(self,limit=16000):
        return 'REFRESH LOG\n'+self._tail(self.work/'last_refresh.log',limit)+'\n\nSERVER LOG\n'+self._tail(self.work/'server.log',min(limit,6000))
