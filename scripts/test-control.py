"""End-to-end localhost API checks. Removes only records created by this run."""
import datetime
import http.cookiejar
import json
import pathlib
import sqlite3
import urllib.error
import urllib.request
import uuid

BASE='http://localhost:3000'
ROOT=pathlib.Path(__file__).resolve().parents[1]
created_jobs=[]
created_plans=[]
checks=0


class Client:
    def __init__(self):
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self,body=None,path='/api/app'):
        req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json','Origin':BASE})
        try:
            with self.opener.open(req,timeout=120) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def login(self,id):
        status,d=self.call(dict(action='login',id=id,password='RailOps@123'));assert status==200,d


def check(label,condition):
    global checks
    assert condition,label
    checks+=1
    print('PASS',label,flush=True)


try:
    anon=Client()
    check('Anonymous planner access denied',anon.call(path='/api/planner')[0]==403)
    controller=Client();controller.login('CONTROL-01')
    status,overview=controller.call()
    check('Completed demo history is explicitly marked',sum(j['status']=='Completed' and j['simulated']==1 and j['created_by']=='DEMO-HISTORY' for j in overview['jobs'])==9)
    check('Controller sees all departments',status==200 and {r['department_code'] for r in overview['departmentRequests']}=={'TRK','SIG','TRC'})
    check('Controller cannot assign operational crews',controller.call(dict(action='assign'))[0]==403)
    head=Client();head.login('HEAD-TRK')
    worker=Client()
    status,d=head.call();wid=next(w['worker_id'] for w in d['workers'] if w['availability_status']=='Available' and w['shift'].startswith('A') and w['station_code'] in ['TNA','DR','KYN','BSR'])
    worker.login(wid)
    check('Head cannot generate controller plans',head.call(dict(action='generate'),'/api/planner')[0]==403)
    check('Worker cannot read planning data',worker.call(path='/api/planner')[0]==403)
    day=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=4)).date().isoformat()
    status,j=head.call(dict(action='create',title='QA control '+uuid.uuid4().hex,description='QA lifecycle verification',department='TRK',station='TNA',location='QA',priority='Medium',required_crew=1,start_at=day+'T08:00+05:30',end_at=day+'T09:00+05:30'))
    assert status==200,j
    jid=j['id'];created_jobs.append(jid)
    distant=next(w['worker_id'] for w in d['workers'] if w['availability_status']=='Available' and w['shift'].startswith('A') and w['station_code']=='SUR')
    check('Distant worker assignment rejected on the server',head.call(dict(action='assign',job_id=jid,worker_ids=[distant],start_at=day+'T08:00+05:30',end_at=day+'T09:00+05:30'))[0]==409)
    status,j=head.call(dict(action='assign',job_id=jid,worker_ids=[wid],start_at=day+'T08:00+05:30',end_at=day+'T09:00+05:30'));assert status==200,j
    check('Cannot complete before starting',worker.call(dict(action='complete_work',job_id=jid))[0]==409)
    check('Cannot start before acknowledging',worker.call(dict(action='start_work',job_id=jid))[0]==409)
    check('Worker acknowledges',worker.call(dict(action='acknowledge',job_id=jid))[0]==200)
    check('Worker starts work',worker.call(dict(action='start_work',job_id=jid))[0]==200)
    _,hd=head.call();check('Started work remains a booking',any(b['job_id']==jid for b in hd['bookings']))
    signal=Client();signal.login('HEAD-SIG')
    check('Head cannot confirm unfinished work',head.call(dict(action='confirm_completion',job_id=jid))[0]==409)
    check('Worker reports completion',worker.call(dict(action='complete_work',job_id=jid))[0]==200)
    _,hd=head.call();job=next(j for j in hd['jobs'] if j['id']==jid)
    check('Completion awaits head review',job['status']=='Awaiting review')
    check('Other department cannot confirm',signal.call(dict(action='confirm_completion',job_id=jid))[0]==409)
    check('Owning head confirms completion',head.call(dict(action='confirm_completion',job_id=jid))[0]==200)
    _,overview=controller.call();job=next(j for j in overview['jobs'] if j['id']==jid)
    check('Controller sees confirmed completion and timestamp',job['status']=='Completed' and job['completed_at'] and job['crew_completed']==1)
    status,hub=controller.call(path='/api/planner')
    check('Authenticated app reaches private planning engine',status==200 and len(hub['dataset']['tasks'])==500)
    try:
        urllib.request.urlopen('http://127.0.0.1:8008/dataset')
        private=False
    except urllib.error.HTTPError as e:private=e.code==403
    check('Direct engine access requires internal token',private)
    with urllib.request.urlopen(BASE+'/node_modules/vite/dist/client/env.mjs') as response:
        client_env=response.read().decode()
    check('Client environment contains no engine token setting','RAILBLOCK_ENGINE_TOKEN' not in client_env)
    status,plan=controller.call(dict(action='generate',config=dict(horizon=7,start_date=day,incidents=[])),'/api/planner')
    assert status==200,plan
    created_plans.append(plan['id'])
    check('Weekly plan persisted with feasible blocks',len(plan['blocks'])>0 and plan['validation']['violations']==0)
    status,reloaded=controller.call(path='/api/planner?id='+plan['id'])
    check('Plan reload preserves exact blocks',status==200 and reloaded['blocks']==plan['blocks'])
    first=plan['blocks'][0]
    body=dict(action='modify',plan_id=plan['id'],revision=plan['revision'],block_id=first['id'],start=600,reason='QA unsafe daytime move')
    check('Unsafe manual modification rejected',controller.call(body,'/api/planner')[0]==409)
    status,accepted=controller.call(dict(action='accept',plan_id=plan['id'],revision=1,reason='QA full plan review'),'/api/planner')
    check('Controller acceptance persisted',status==200 and accepted['status']=='Accepted' and accepted['revision']==2)
    check('Stale review cannot overwrite decision',controller.call(dict(action='reject',plan_id=plan['id'],revision=1,reason='QA stale decision'),'/api/planner')[0]==409)
    status,hub=controller.call(path='/api/planner')
    check('Review feedback persisted',any(f['plan_id']==plan['id'] and f['decision']=='Accepted' for f in hub['feedback']))
    # A no-op time edit still goes through complete feasibility validation and returns to draft.
    status,modified=controller.call(dict(action='modify',plan_id=plan['id'],revision=2,block_id=first['id'],start=first['start'],reason='QA retain reviewed start'),'/api/planner')
    check('Safe human edit revalidates and requires renewed review',status==200 and modified['status']=='Draft' and modified['comparison'] is None)
    status,rejected=controller.call(dict(action='reject',plan_id=plan['id'],revision=3,reason='QA archive run'),'/api/planner')
    check('Whole-plan rejection archived',status==200 and rejected['status']=='Rejected')
    check('Archived plan cannot be reoptimized',controller.call(dict(action='reoptimize',plan_id=plan['id'],revision=4,incident=dict(kind='freight',section=first['section'],start=0,end=60)),'/api/planner')[0]==409)
    print(f'\n{checks} Control Centre checks passed.',flush=True)
finally:
    for path in (ROOT/'.wrangler/state/v3/d1/miniflare-D1DatabaseObject').glob('*.sqlite'):
        con=sqlite3.connect(path)
        if con.execute("SELECT name FROM sqlite_master WHERE name='planner_plans'").fetchone():
            for id in created_plans:
                con.execute('DELETE FROM planner_feedback WHERE plan_id=?',(id,));con.execute('DELETE FROM planner_plans WHERE id=?',(id,))
            for id in created_jobs:
                con.execute('DELETE FROM assignments WHERE job_id=?',(id,));con.execute('DELETE FROM jobs WHERE id=?',(id,))
            con.commit()
        con.close()
    print('Removed this run’s test jobs and plans; existing user records preserved.',flush=True)
