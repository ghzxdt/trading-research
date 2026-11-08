"""Desktop ownership, busy-writer protection and recovery regressions."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app_control as control
import hub_server as hub

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'work'/'desktop_control_tests'
SCRATCH.mkdir(parents=True,exist_ok=True)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH);self.root=Path(self.tmp.name)
        self.controller=control.Controller(self.root,8766)
        self.idle={'running':True,'identity_ok':True,'busy':False,'build_lock':{'stale':False},'build':{},'message':'Ready'}
    def tearDown(self):self.tmp.cleanup()

    def test_start_reuses_identified_server(self):
        with patch.object(self.controller,'status',return_value=self.idle),patch.object(control.subprocess,'Popen') as spawn:
            self.assertTrue(self.controller.start()['identity_ok']);spawn.assert_not_called()

    def test_foreign_or_legacy_service_is_never_stopped(self):
        foreign={**self.idle,'identity_ok':False,'message':'Unknown service'}
        with patch.object(self.controller,'status',return_value=foreign),patch.object(self.controller,'_request') as req,patch.object(control.subprocess,'Popen') as spawn:
            for action in (self.controller.start,self.controller.stop,self.controller.restart):
                with self.assertRaises(control.ControlError):action()
            req.assert_not_called();spawn.assert_not_called()

    def test_busy_build_prevents_stop_and_restart(self):
        with patch.object(self.controller,'status',return_value={**self.idle,'busy':True}),patch.object(self.controller,'_request') as req:
            with self.assertRaises(control.ControlError):self.controller.stop()
            with self.assertRaises(control.ControlError):self.controller.restart()
            req.assert_not_called()

    def test_refresh_calls_requested_mode(self):
        with patch.object(self.controller,'start',return_value=self.idle),patch.object(self.controller,'status',return_value=self.idle),patch.object(self.controller,'_request',return_value={'ok':True}) as req:
            self.controller.refresh(offline=True);req.assert_called_once_with('/api/rebuild',method='POST')

    def test_busy_refresh_does_not_start_another(self):
        with patch.object(self.controller,'start',return_value={**self.idle,'busy':True}),patch.object(self.controller,'_request') as req:
            with self.assertRaises(control.ControlError):self.controller.refresh()
            req.assert_not_called()

    def test_verified_stale_lock_is_preserved_as_diagnostic(self):
        lock=self.root/'.build.lock';lock.write_text('123456789')
        marker=self.root/'paper.log';marker.write_bytes(b'paper records unchanged')
        with patch.object(control,'process_alive',return_value=False),patch.object(control,'active_descendants',return_value=[]),patch.object(self.controller,'status',return_value={'running':False,'busy':False}):
            result=self.controller.recover_stale_lock()
        self.assertTrue(result['recovered']);self.assertFalse(lock.exists())
        self.assertEqual(Path(result['saved_lock']).read_text(),'123456789')
        self.assertEqual(marker.read_bytes(),b'paper records unchanged')

    def test_live_or_uncheckable_pid_lock_is_not_cleared(self):
        lock=self.root/'.build.lock';lock.write_text('123456789')
        for alive in (True,None):
            with self.subTest(alive=alive),patch.object(control,'process_alive',return_value=alive):
                with self.assertRaises(control.ControlError):self.controller.recover_stale_lock()
                self.assertEqual(lock.read_text(),'123456789')

    def test_surviving_children_prevent_recovery(self):
        lock=self.root/'.build.lock';lock.write_text('123456789')
        with patch.object(control,'process_alive',return_value=False),patch.object(control,'active_descendants',return_value=[17]):
            self.assertTrue(control.build_lock_state(self.root)['busy'])
            with self.assertRaises(control.ControlError):self.controller.recover_stale_lock()
        self.assertTrue(lock.exists())

    def test_malformed_lock_is_not_guessed_away(self):
        lock=self.root/'.build.lock';lock.write_text('unknown owner')
        with self.assertRaises(control.ControlError):self.controller.recover_stale_lock()
        self.assertTrue(lock.exists())

    def test_pid_larger_than_windows_dword_is_unknown(self):
        self.assertIsNone(control.process_alive(0x100000001))

    def test_status_rejects_wrong_identity(self):
        with patch.object(self.controller,'_request',return_value={'ok':True,'app_id':'another-app','build':{}}):
            state=self.controller.status()
        self.assertTrue(state['running']);self.assertFalse(state['identity_ok'])

    def test_log_reader_is_bounded_and_handles_missing_files(self):
        self.assertIn('No log',self.controller.last_log())
        self.controller.work.mkdir();(self.controller.work/'last_refresh.log').write_text('A'*20000)
        self.assertLess(len(self.controller.last_log(limit=1000)),1200)

    def test_real_process_snapshot_does_not_require_termination_rights(self):
        with subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.5)'],creationflags=control.hidden_process_flags()) as child:
            self.assertTrue(control.process_alive(child.pid))
            descendants=control.active_descendants(os.getpid())
            self.assertIsNotNone(descendants);self.assertIn(child.pid,descendants)
            child.wait(timeout=3)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH);self.root=Path(self.tmp.name)
        self.patches=[patch.object(hub,'ROOT',self.root),patch.object(hub,'OUT',self.root/'output'),patch.object(hub,'WORK',self.root/'work')]
        for p in self.patches:p.start()
        self.saved=dict(hub.BUILD_STATE)
        with hub.STATE_LOCK:hub.BUILD_STATE.clear();hub.BUILD_STATE.update(running=False,ok=None,message='Ready',action=None)
    def tearDown(self):
        with hub.STATE_LOCK:hub.BUILD_STATE.clear();hub.BUILD_STATE.update(self.saved)
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def handler(self,secret='x'*32):
        cls=hub.make_handler(8766,None,token=secret);handler=object.__new__(cls)
        handler.headers={'Host':'127.0.0.1:8766','X-Hub':'1'}
        handler.path='/api/shutdown';handler._json=Mock();handler.server=SimpleNamespace(shutdown=Mock())
        return handler

    def test_shutdown_requires_private_local_secret(self):
        handler=self.handler();handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0],403)
        handler.server.shutdown.assert_not_called()

    def test_busy_shutdown_is_refused_even_with_secret(self):
        handler=self.handler();handler.headers['X-Local-Control']='x'*32
        with patch.object(hub,'build_lock_state',return_value={'busy':True}):handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0],409)
        handler.server.shutdown.assert_not_called()

    def test_idle_authenticated_shutdown_is_deferred_to_thread(self):
        handler=self.handler();handler.headers['X-Local-Control']='x'*32
        with patch.object(hub,'status_payload',return_value={'busy':False}),patch.object(hub.threading,'Thread') as thread:
            handler.do_POST();thread.assert_called_once_with(target=handler.server.shutdown,daemon=True)
        self.assertEqual(handler._json.call_args.args[0],200)

    def test_shutdown_reservation_blocks_new_refresh(self):
        handler=self.handler();handler.headers['X-Local-Control']='x'*32
        with patch.object(hub,'build_lock_state',return_value={'busy':False}),patch.object(hub.threading,'Thread'):
            handler.do_POST()
        newer=object.__new__(type(handler));newer.headers={'Host':'127.0.0.1:8766','X-Hub':'1'}
        newer.path='/api/rebuild';newer._json=Mock()
        newer.do_POST()
        self.assertEqual(newer._json.call_args.args[0],503)
        self.assertFalse(hub.LOCK.locked())

    def test_secret_persists_and_is_not_exposed_in_status(self):
        first=hub.control_secret();self.assertEqual(first,hub.control_secret())
        self.assertNotIn(first,json.dumps(hub.status_payload()))
        self.assertEqual(hub.status_payload()['app_id'],control.app_identity(self.root))

    def test_last_refresh_status_survives_restart(self):
        hub.update_build_state(running=False,ok=True,message='Completed refresh',finished_at='test')
        with hub.STATE_LOCK:hub.BUILD_STATE.clear()
        hub.load_build_state();self.assertTrue(hub.BUILD_STATE['ok']);self.assertEqual(hub.BUILD_STATE['message'],'Completed refresh')

    def test_interrupted_status_is_not_reported_as_success(self):
        hub.update_build_state(running=True,ok=None,message='In progress')
        hub.load_build_state();self.assertFalse(hub.BUILD_STATE['running']);self.assertFalse(hub.BUILD_STATE['ok'])

if __name__=='__main__':unittest.main()
