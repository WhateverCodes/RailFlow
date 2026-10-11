"""Check maintenance dataset integration against live localhost APIs and preserve user data."""
import concurrent.futures,datetime,http.cookiejar,json,pathlib,sqlite3,urllib.request,urllib.error
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE='http://localhost:3000'
expected=json.loads((ROOT/'data/maintenance-requests.json').read_text())
created=[];checks=[]
class Client:
 def __init__(self):self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def call(self,body=None):
  req=urllib.request.Request(BASE+'/api/app',data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json','Origin':BASE})
  try:
   with self.opener.open(req,timeout=30) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def login(self,id):assert self.call({'action':'login','id':id,'password':'RailOps@123'})[0]==200
 def get(self):
  status,data=self.call();assert status==200,data;return data

def check(label,condition):
 assert condition,label
 checks.append(label);print('PASS',label,flush=True)

def plan(client,request,count=6,minutes=None,station='TNA',record=True):
 day=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=4)).date()
 start=datetime.datetime.combine(day,datetime.time(8),datetime.timezone(datetime.timedelta(hours=5,minutes=30)))
 end=start+datetime.timedelta(minutes=request['required_duration_mins'] if minutes is None else minutes)
 body={'action':'create_from_request','request_id':request['request_id'],'station':station,'required_crew':count,'priority':'High','start_at':start.isoformat(),'end_at':end.isoformat(),'title':'Spoofed title','location':'Spoofed location','department':'Spoofed department'}
 status,data=client.call(body)
 if status==200 and record:created.append(data['id'])
 return status,data,body

try:
 heads={};responses={}
 for dept,count in [('TRK',549),('SIG',292),('TRC',159)]:
  c=Client();c.login('HEAD-'+dept);data=c.get();heads[dept]=c;responses[dept]=data
  check(f'{dept}: all {count} requests visible only to their department',len(data['requests'])==count and all(r['department_code']==dept for r in data['requests']))
  observed={r['request_id']:r for r in data['requests']};source=[r for r in expected if r['department_code']==dept]
  check(f'{dept}: every imported CSV field matches exactly',all(all(observed[r['request_id']][k]==v for k,v in r.items()) for r in source))
 check('Dataset manifest reports all 1,000 source records',all(d['requestDataset']['row_count']==1000 for d in responses.values()))
 track=next(r for r in responses['TRK']['requests'] if not r['job_id'])
 check('Other department cannot create job from Track request',plan(heads['SIG'],track)[0]==404)
 check('Unknown request rejected',plan(heads['TRK'],{**track,'request_id':'MISSING-REQUEST'})[0]==404)
 check('Missing reporting station rejected without inventing one',plan(heads['TRK'],track,station='')[0]==400)
 check('Missing crew count rejected',plan(heads['TRK'],track,count=0)[0]==400)
 check('Shorter than source duration rejected at planning',plan(heads['TRK'],track,minutes=1)[0]==400)
 for dept in ['TRK','SIG','TRC']:
  head=heads[dept];initial=responses[dept];r=next(r for r in initial['requests'] if not r['job_id'])
  status,result,body=plan(head,r);assert status==200,result
  jobid=result['id'];current=head.get();job=next(j for j in current['jobs'] if j['id']==jobid)
  check(f'{dept}: linked job uses source title, corridor, department and request ID',job['title']==r['task_type'] and job['location']==r['corridor_name']+' · '+r['line_type'] and job['department']==dept and job['source_request_id']==r['request_id'])
  check(f'{dept}: report timestamp preserved separately from planned start',job['source_request']['timestamp']==r['timestamp'] and job['start_at']!=r['timestamp'])
  start=datetime.datetime.fromisoformat(job['start_at'].replace('Z','+00:00'));end=datetime.datetime.fromisoformat(job['end_at'].replace('Z','+00:00'))
  check(f'{dept}: required source duration retained',int((end-start).total_seconds()/60)==r['required_duration_mins'])
  ids=[w['worker_id'] for w in current['workers'] if w['availability_status']=='Available' and w['shift'].startswith('A') and w['station_code'] in ['TNA','DR','KYN','BSR']][:6];assert len(ids)==6
  short={**body,'action':'assign','job_id':jobid,'worker_ids':ids,'end_at':(start+datetime.timedelta(minutes=1)).isoformat()}
  check(f'{dept}: source duration cannot be shortened during crew assignment',head.call(short)[0]==400)
  result=head.call({**body,'action':'assign','job_id':jobid,'worker_ids':ids});assert result[0]==200,result
  check(f'{dept}: six selected workers assigned to imported request',next(j for j in head.get()['jobs'] if j['id']==jobid)['crew_count']==6)
  check(f'{dept}: duplicate plan for same request rejected',plan(head,r)[0]==409)
  updated=next(x for x in head.get()['requests'] if x['request_id']==r['request_id'])
  check(f'{dept}: source register links to assigned job',updated['job_id']==jobid and updated['job_status']=='Assigned')
  w=Client();w.login(ids[0]);personal=w.get();wj=next(j for j in personal['jobs'] if j['id']==jobid)
  check(f'{dept}: assigned worker receives linked coordinates and exact job time',wj['source_request']['latitude']==r['latitude'] and wj['source_request']['longitude']==r['longitude'] and wj['start_at']==job['start_at'] and 'requests' not in personal)
  check(f'{dept}: worker cannot plan source requests',plan(w,r)[0]==403)
  outsider=Client();outsider.login(next(w['worker_id'] for w in initial['workers'] if w['worker_id'] not in ids));personal=outsider.get()
  check(f'{dept}: unselected worker cannot see imported assignment',all(j['id']!=jobid for j in personal['jobs']) and 'requests' not in personal)
 race=next(r for r in heads['TRK'].get()['requests'] if not r['job_id']);other=Client();other.login('HEAD-TRK')
 with concurrent.futures.ThreadPoolExecutor() as pool:
  a=pool.submit(plan,heads['TRK'],race,1,None,'PUNE',False);b=pool.submit(plan,other,race,1,None,'PUNE',False);results=[a.result(),b.result()]
 for status,result,_ in results:
  if status==200:created.append(result['id'])
 check('Simultaneous planning creates only one job for a source request',sorted(x[0] for x in results)==[200,409])
 check('Repeated reads do not duplicate imported rows',sum(len(heads[dept].get()['requests']) for dept in heads)==1000)
 print(f'\n{len(checks)} dataset integration checks passed.')
finally:
 for p in (ROOT/'.wrangler/state/v3/d1/miniflare-D1DatabaseObject').glob('*.sqlite'):
  c=sqlite3.connect(p)
  if c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
   for id in created:
    c.execute('DELETE FROM assignments WHERE job_id=?',(id,));c.execute('DELETE FROM jobs WHERE id=?',(id,))
   c.commit();print(f'Cleaned {len(created)} request test jobs; imported records and user work preserved.')
  c.close()
