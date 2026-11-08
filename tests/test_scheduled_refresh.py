"""Scheduled evening refresh: VIX wait, deadline, app refresh path and the git data backup."""
import json, shutil, subprocess, tempfile, unittest
from datetime import date
from pathlib import Path

import pandas as pd

import git_backup
import scheduled_refresh as sr
from app_control import ControlError
from monitor import paper
from validation import NY, expected_session

ROOT=Path(__file__).resolve().parents[1]
SCRATCH=ROOT/'work'/'scheduled_refresh_tests'
SCRATCH.mkdir(parents=True,exist_ok=True)
MONDAY_EVENING=pd.Timestamp('2026-11-09 16:45',tz=NY)


class FakeClock:
    def __init__(self,start):self.t=start;self.slept=[]
    def now(self):return self.t
    def sleep(self,seconds):self.slept.append(seconds);self.t+=pd.Timedelta(seconds=seconds)


class FakeController:
    def __init__(self,statuses,refresh_error=None):
        self.statuses=list(statuses);self.refresh_error=refresh_error;self.refreshed=0;self.stopped=0;self.forced=[]
    def status(self):return self.statuses.pop(0) if len(self.statuses)>1 else self.statuses[0]
    def refresh(self,offline=False,allow_data_blocked=False):
        if self.refresh_error:raise ControlError(self.refresh_error)
        self.refreshed+=1;self.forced.append(allow_data_blocked)
    def stop(self):self.stopped+=1


IDLE_DONE={'running':True,'identity_ok':True,'busy':False,'build':{'running':False,'ok':True}}
BUSY={'running':True,'identity_ok':True,'busy':True,'build':{'running':True}}


class ScheduleTests(unittest.TestCase):
    def test_newest_csv_date_skips_blank_and_junk_lines(self):
        text='DATE,OPEN,HIGH,LOW,CLOSE\n11/05/2026,1,2,1,2\n11/06/2026,1,2,1,2\n\nnot a row\n'
        self.assertEqual(sr.newest_csv_date(text),date(2026,11,6))
        self.assertIsNone(sr.newest_csv_date('DATE,CLOSE\n'))

    def test_deadline_is_before_next_open_and_never_past_next_morning(self):
        cases=[('2026-11-09 16:45','2026-11-10 09:00'),  # Monday evening -> Tuesday before the open
               ('2026-11-13 16:45','2026-11-14 09:00'),  # Friday evening -> Saturday morning, not Monday
               ('2026-11-10 07:00','2026-11-10 09:00'),  # missed run caught up before the open
               ('2026-11-26 16:45','2026-11-27 09:00')]  # Thanksgiving: Wednesday's session, Friday's open
        for start,expected in cases:
            s=pd.Timestamp(start,tz=NY)
            self.assertEqual(sr.deadline_for(s,expected_session(s)),pd.Timestamp(expected,tz=NY),start)


class RunTests(unittest.TestCase):
    def setUp(self):self.clock=FakeClock(MONDAY_EVENING);self.said=[];self.backups=0

    def go(self,vix,states,refresh):
        def backup():self.backups+=1
        return sr.run(Path('.'),say=self.said.append,now=self.clock.now,sleep=self.clock.sleep,
                      vix_date=vix,states=lambda root,session:states(),refresh=refresh,backup=backup)

    def test_already_logged_skips_refresh_but_still_backs_up(self):
        calls=[]
        code=self.go(lambda:calls.append('vix'),lambda:{'k':'recorded_before_entry'},lambda force:calls.append('refresh'))
        self.assertEqual((code,calls,self.backups),(0,[],1))

    def test_waits_for_vix_then_refreshes_once_without_forcing(self):
        posted=iter([date(2026,11,6),date(2026,11,6),date(2026,11,9)]);refreshes=[]
        def refresh(force):refreshes.append((self.clock.t,force));return 'Refresh succeeded.'
        code=self.go(lambda:next(posted),lambda:{'k':'recorded_before_entry'} if refreshes else None,refresh)
        self.assertEqual(code,0)
        self.assertEqual(refreshes,[(MONDAY_EVENING+pd.Timedelta(minutes=30),False)])
        self.assertEqual(self.clock.slept,[900.0,900.0])

    def test_failed_refresh_is_retried(self):
        refreshes=[]
        def refresh(force):refreshes.append(force);return 'Refresh failed: Yahoo'
        code=self.go(lambda:date(2026,11,9),lambda:{'k':'recorded_before_entry'} if len(refreshes)>=2 else None,refresh)
        self.assertEqual((code,refreshes),(0,[False,False]))

    def test_deadline_without_vix_forces_one_refresh_and_reports_data_blocked(self):
        refreshes=[]
        def refresh(force):refreshes.append((self.clock.t,force));return 'Refresh succeeded.'
        code=self.go(lambda:date(2026,11,6),lambda:{'k':'data_blocked'} if refreshes else None,refresh)
        self.assertEqual(code,1)
        self.assertEqual(refreshes,[(pd.Timestamp('2026-11-10 09:00',tz=NY),True)])

    def test_nothing_logged_by_deadline_returns_2(self):
        refreshes=[]
        code=self.go(lambda:date(2026,11,6),lambda:None,lambda force:refreshes.append(force) or 'Refresh failed: x')
        self.assertEqual((code,refreshes,self.backups),(2,[True],1))
        self.assertLessEqual(self.clock.t,pd.Timestamp('2026-11-10 09:00',tz=NY))

    def test_vix_download_errors_count_as_not_posted(self):
        def vix():raise OSError('offline')
        code=self.go(vix,lambda:None,lambda force:'Refresh failed: offline')
        self.assertEqual(code,2)
        self.assertTrue(any("Could not read Cboe" in s for s in self.said))


class AppRefreshTests(unittest.TestCase):
    def test_starts_refresh_waits_and_stops_server_it_started(self):
        c=FakeController([{'running':False,'busy':False},BUSY,BUSY,IDLE_DONE])
        self.assertEqual(sr.app_refresh(c,say=lambda m:None,sleep=lambda s:None),'Refresh succeeded.')
        self.assertEqual((c.refreshed,c.stopped,c.forced),(1,1,[False]))

    def test_force_overrides_the_vix_guard(self):
        c=FakeController([IDLE_DONE,BUSY,IDLE_DONE])
        sr.app_refresh(c,say=lambda m:None,sleep=lambda s:None,force=True)
        self.assertEqual(c.forced,[True])

    def test_running_refresh_is_waited_for_not_doubled(self):
        c=FakeController([BUSY,BUSY,IDLE_DONE])
        out=sr.app_refresh(c,say=lambda m:None,sleep=lambda s:None)
        self.assertTrue(out.startswith('A refresh was already running'))
        self.assertEqual((c.refreshed,c.stopped),(0,0))

    def test_foreign_port_owner_is_left_alone(self):
        c=FakeController([{'running':True,'identity_ok':False,'message':'Unknown service'}])
        self.assertEqual(sr.app_refresh(c,say=lambda m:None),'Refresh not started: Unknown service')
        self.assertEqual((c.refreshed,c.stopped),(0,0))

    def test_failed_build_is_reported(self):
        failed={'running':True,'identity_ok':True,'busy':False,'build':{'running':False,'ok':False,'message':'Build failed'}}
        c=FakeController([IDLE_DONE,BUSY,failed])
        self.assertEqual(sr.app_refresh(c,say=lambda m:None,sleep=lambda s:None),'Refresh failed: Build failed')


class DecisionStateTests(unittest.TestCase):
    def test_states_need_every_frozen_rule(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
            root=Path(tmp);(root/'data/monitor').mkdir(parents=True)
            (root/'data/monitor/experiment_lock.json').write_text(json.dumps({'version':'v1','strategies':[{'id':'a'},{'id':'b'}]}),encoding='utf-8')
            log=root/'data/monitor/paper_events.jsonl';events=[]
            paper.append(log,events,{'type':'decision','key':'v1:2026-11-09:a','state':'recorded_before_entry'})
            self.assertIsNone(sr.decision_states(root,pd.Timestamp('2026-11-09')))
            paper.append(log,events,{'type':'decision','key':'v1:2026-11-09:b','state':'data_blocked'})
            self.assertEqual(sr.decision_states(root,pd.Timestamp('2026-11-09')),
                             {'v1:2026-11-09:a':'recorded_before_entry','v1:2026-11-09:b':'data_blocked'})


@unittest.skipUnless(shutil.which('git'),'git is not installed')
class GitBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=SCRATCH,ignore_cleanup_errors=True)
        self.root=Path(self.tmp.name)/'app';self.root.mkdir();self.said=[]
        self.git('init','-q','-b','main');self.git('config','user.name','Test');self.git('config','user.email','test@example.invalid')
        self.git('config','commit.gpgsign','false')
        (self.root/'data/monitor').mkdir(parents=True);(self.root/'data/kalshi').mkdir(parents=True)
        self.log=self.root/'data/monitor/paper_events.jsonl';self.events=[]
        paper.append(self.log,self.events,{'type':'decision','key':'k1','state':'recorded_before_entry'})
        (self.root/'data/kalshi/snapshots.csv').write_text('a,b\n1,2\n',encoding='utf-8')
        (self.root/'data/monitor/experiment_lock.json').write_text('{}',encoding='utf-8')
        (self.root/'app.py').write_text('x = 1\n',encoding='utf-8')
        self.git('add','-A');self.git('commit','-q','-m','initial')
    def tearDown(self):self.tmp.cleanup()

    def git(self,*args,cwd=None):
        return subprocess.run(['git',*args],cwd=cwd or self.root,check=True,capture_output=True,text=True).stdout.strip()

    def refresh_data(self):
        paper.append(self.log,self.events,{'type':'decision','key':'k2','state':'recorded_before_entry'})
        with (self.root/'data/kalshi/snapshots.csv').open('a',encoding='utf-8') as f:f.write('3,4\n')
        (self.root/'data/employment').mkdir(exist_ok=True)
        (self.root/'data/employment/refresh_status.json').write_text('{}',encoding='utf-8')

    def test_commits_only_data_and_leaves_code_changes_alone(self):
        self.refresh_data();(self.root/'app.py').write_text('x = 2\n',encoding='utf-8')
        self.assertEqual(git_backup.sync(self.root,self.said.append,'Evening refresh data, test'),'committed')
        self.assertEqual(sorted(self.git('show','--name-only','--format=','HEAD').split()),
                         ['data/employment/refresh_status.json','data/kalshi/snapshots.csv','data/monitor/paper_events.jsonl'])
        self.assertIn('M app.py',self.git('status','--porcelain'))
        self.assertTrue(any('No GitHub remote' in s for s in self.said))

    def test_pushes_main_to_origin(self):
        remote=Path(self.tmp.name)/'remote.git'
        self.git('init','-q','--bare','-b','main',str(remote),cwd=self.tmp.name);self.git('remote','add','origin',str(remote))
        self.refresh_data()
        self.assertEqual(git_backup.sync(self.root,self.said.append),'committed')
        self.assertEqual(self.git('rev-parse','HEAD'),self.git('--git-dir',str(remote),'rev-parse','main'))

    def test_other_branch_is_skipped(self):
        self.git('checkout','-q','-b','feature');head=self.git('rev-parse','HEAD');self.refresh_data()
        self.assertEqual(git_backup.sync(self.root,self.said.append),'skipped')
        self.assertEqual(self.git('rev-parse','HEAD'),head)

    def test_broken_paper_chain_is_not_committed(self):
        head=self.git('rev-parse','HEAD')
        with self.log.open('a',encoding='utf-8') as f:f.write('{"type": "decision", "hash": "forged"}\n')
        self.assertEqual(git_backup.sync(self.root,self.said.append),'refused')
        self.assertEqual(self.git('rev-parse','HEAD'),head)

    def test_frozen_experiment_lock_is_never_committed(self):
        self.refresh_data();(self.root/'data/monitor/experiment_lock.json').write_text('{"changed": true}',encoding='utf-8')
        git_backup.sync(self.root,self.said.append)
        self.assertNotIn('data/monitor/experiment_lock.json',self.git('show','--name-only','--format=','HEAD').split())
        self.assertTrue(any('frozen' in s for s in self.said))

    def test_nothing_changed_makes_no_commit(self):
        head=self.git('rev-parse','HEAD')
        self.assertEqual(git_backup.sync(self.root,self.said.append),'nothing to commit')
        self.assertEqual(self.git('rev-parse','HEAD'),head)


if __name__=='__main__':unittest.main()
