"""Local API integration checks. Every job/request fixture is uniquely labelled and removed."""
import concurrent.futures
import datetime as dt
import http.cookiejar
import json
import pathlib
import sqlite3
import urllib.error
import urllib.request
import uuid

ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE='http://localhost:3000'
PREFIX='QAOPS-'+uuid.uuid4().hex[:10]
plans=[];request_ids=[];checks=0
day=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=60)).date().isoformat()


class Client:
    def __init__(self):self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self,body=None,path='/api/operations',pdf=False):
        req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':BASE})
        try:
            with self.opener.open(req,timeout=120) as r:return r.status,r.read() if pdf else json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def login(self,id):
        code,value=self.call(dict(action='login',id=id,password='RailOps@123'),'/api/app');assert code==200,value


def check(label,ok):
    global checks
    assert ok,label
    checks+=1;print('PASS',label,flush=True)


def connection():
    for p in (ROOT/'.wrangler/state/v3/d1').rglob('*.sqlite'):
        db=sqlite3.connect(p,timeout=20)
        if db.execute("SELECT count(*) FROM sqlite_master WHERE name='operations_state'").fetchone()[0]:return db
        db.close()
    raise RuntimeError('Local operations database not found.')


def save(kind,record):
    _,state=controller.call();code,value=controller.call(dict(action='save_record',kind=kind,record=record,revision=state['revision']))
    assert code==200,value


def generate():
    _,state=controller.call();code,p=controller.call(dict(action='generate',revision=state['revision'],start_date=day,horizon=1,request_ids=request_ids))
    assert code==200,p;plans.append(p['id']);return p


def review(action,p):
    return controller.call(dict(action=action,plan_id=p['id'],revision=p['revision'],reason=PREFIX+' integration check'))


try:
    controller=Client();controller.login('CONTROL-01')
    check('Anonymous operations denied',Client().call()[0]==401)
    head=Client();head.login('HEAD-TRK')
    check('Head cannot access controller input register',head.call()[0]==403)
    check('Anonymous model access denied',Client().call(path='/api/models')[0]==401)
    check('Head cannot train or inspect freight models',head.call(path='/api/models')[0]==403)
    _,state=controller.call();check('Source datasets available',len(state['requests'])>=1000)
    with connection() as db:
        for dep,source,duration in [('TRK','TMS',60),('SIG','SMMS',30),('TRC','TDMS',45)]:
            rid=PREFIX+'-'+dep;request_ids.append(rid)
            db.execute('INSERT INTO maintenance_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(rid,source,dep,'QA integration inspection','Pune-Lonavala','UP Line',73.8,18.5,3,10,duration,'QA fixture'))
    section=dict(id=PREFIX,corridor='Pune-Lonavala',name=PREFIX+' temporary test section',from_station='PUNE',to_station='LNL',source=PREFIX+' integration test only')
    save('sections',section)
    window=dict(id=PREFIX+'-WINDOW',section_id=PREFIX,start_at=day+'T06:00:00+05:30',end_at=day+'T14:00:00+05:30',power=False,traffic_complete=False,reference=PREFIX+' synthetic test window, not railway authorization')
    save('windows',window)
    for rid in request_ids:
        save('tasks',dict(request_id=rid,section_id=PREFIX,station='PUNE',crew=1,release_at=day+'T06:00:00+05:30',due_at=day+'T14:00:00+05:30',machine='',power=False,compatibility_group=PREFIX,compatibility_reference=PREFIX+' synthetic compatibility',location_reference=PREFIX+' synthetic location'))
    _,state=controller.call()
    code,error=controller.call(dict(action='import',revision=state['revision'],kind='movements',csv='id,section_id\na,b'))
    check('Invalid CSV rejected atomically',code==400 and controller.call()[1]['revision']==state['revision'])
    check('Stale input write rejected',controller.call(dict(action='remove_record',revision=0,kind='sections',id=PREFIX))[0]==409)
    p=generate();check('Supplied requests form a joint block',len(p['payload']['blocks'])==1 and len(p['payload']['blocks'][0]['tasks'])==3)
    code,accepted=review('accept',p);assert code==200,accepted
    check('Incomplete traffic cannot release jobs',review('release',accepted)[0]==409)
    window['traffic_complete']=True;save('windows',window)
    check('Changed input invalidates earlier acceptance',review('release',accepted)[0]==409)
    p=generate();code,p=review('accept',p);assert code==200,p
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        responses=list(pool.map(lambda _:review('release',p),range(2)))
    check('Concurrent release creates jobs once',sorted(r[0] for r in responses)==[200,409])
    released=next(r[1] for r in responses if r[0]==200)
    _,jobs=head.call(path='/api/app');job=next(j for j in jobs['jobs'] if j['source_request_id']==request_ids[0])
    check('Released job enters owning head workspace with locked time',job['status']=='Pending' and bool(job['approved_block']))
    worker=next(w for w in jobs['workers'] if w['availability_status']=='Available' and w['station_code'] in ['PUNE','LNL'] and w['shift'].startswith('A'))
    body=dict(action='assign',job_id=job['id'],worker_ids=[worker['worker_id']],start_at=job['start_at'],end_at=job['end_at'])
    changed={**body,'end_at':(dt.datetime.fromisoformat(job['end_at'].replace('Z','+00:00'))+dt.timedelta(minutes=1)).isoformat()}
    check('Approved block cannot be shifted by head',head.call(changed,'/api/app')[0]==409)
    code,value=head.call(body,'/api/app');assert code==200,value
    wc=Client();wc.login(worker['worker_id'])
    _,worker_jobs=wc.call(path='/api/app');check('Selected worker sees released job',any(j['id']==job['id'] for j in worker_jobs['jobs']))
    check('Worker acknowledges released job',wc.call(dict(action='acknowledge',job_id=job['id']),'/api/app')[0]==200)
    check('Worker cannot start outside approved block',wc.call(dict(action='start_work',job_id=job['id']),'/api/app')[0]==409)
    check('Worker cannot export controller plan',wc.call(path=f'/api/reports?kind=operations&plan_id={released["id"]}&revision={released["revision"]}')[0]==403)
    check('Stale report revision denied',controller.call(path=f'/api/reports?kind=operations&plan_id={released["id"]}&revision=1')[0]==409)
    outputs=ROOT/'tmp'/'pdfs';outputs.mkdir(parents=True,exist_ok=True)
    for client,path,name in [(controller,f'/api/reports?kind=operations&plan_id={released["id"]}&revision={released["revision"]}','operations-plan.pdf'),(head,f'/api/reports?kind=job&job_id={job["id"]}','operations-crew.pdf'),(wc,f'/api/reports?kind=daily&date={day}','operations-worker-day.pdf'),(controller,f'/api/reports?kind=daily&date={day}','operations-controller-day.pdf')]:
        code,pdf=client.call(path=path,pdf=True);check(name+' is a server-generated PDF',code==200 and isinstance(pdf,bytes) and pdf.startswith(b'%PDF-'));(outputs/name).write_bytes(pdf)
    check('Worker identity cannot be overridden',wc.call(path=f'/api/reports?kind=daily&date={day}&worker_id=W0001')[0]==403)
    movement=dict(id=PREFIX+'-DELAY',section_id=PREFIX,train_no='QA-FREIGHT',kind='Freight',start_at=job['start_at'],end_at=job['end_at'],source=PREFIX+' delay test')
    save('movements',movement)
    check('Changed train movement raises released-work alert',any(a['plan_id']==released['id'] for a in controller.call()[1]['alerts']))
    _,model=controller.call(path='/api/models');check('No observed-history model falsely active',model['active'] is None)
    print(f'{checks} operations API checks passed.',flush=True)
finally:
    with connection() as db:
        for p in plans:
            ids=[r[0] for r in db.execute('SELECT job_id FROM operations_jobs WHERE plan_id=?',(p,))]
            for jid in ids:db.execute('DELETE FROM assignments WHERE job_id=?',(jid,))
            db.execute('DELETE FROM operations_jobs WHERE plan_id=?',(p,))
            for jid in ids:db.execute('DELETE FROM jobs WHERE id=?',(jid,))
            db.execute('DELETE FROM operations_audit WHERE entity_id=?',(p,));db.execute('DELETE FROM operations_plans WHERE id=?',(p,))
        row=db.execute("SELECT payload FROM operations_state WHERE id='main'").fetchone()
        if row:
            payload=json.loads(row[0])
            for key in ['sections','movements','windows','tasks']:
                payload[key]=[r for r in payload[key] if not str(r.get('id',r.get('request_id',''))).startswith(PREFIX)]
            db.execute("UPDATE operations_state SET payload=?,revision=revision+1 WHERE id='main'",(json.dumps(payload),))
        for rid in request_ids:db.execute('DELETE FROM maintenance_requests WHERE request_id=?',(rid,))
    print('Removed this run’s temporary requests, jobs, plans and input records.',flush=True)
