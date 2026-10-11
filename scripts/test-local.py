"""Exercise real localhost APIs; remove only the test jobs created by this run."""
import concurrent.futures,datetime,http.cookiejar,json,pathlib,sqlite3,urllib.request,urllib.error,uuid
ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE='http://localhost:3000'
created=[]
checks=[]
class Client:
 def __init__(self): self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def request(self,body=None):
  req=urllib.request.Request(BASE+'/api/app',data=json.dumps(body).encode() if body else None,headers={'Content-Type':'application/json','Origin':BASE})
  try:
   with self.opener.open(req,timeout=20) as r:return r.status,json.load(r)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def login(self,id):
  status,data=self.request({'action':'login','id':id,'password':'RailOps@123'});assert status==200,(status,data)
def check(label,test):
 assert test,label
 checks.append(label);print('PASS',label,flush=True)
day=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=2)).date().isoformat()
def time(hour):return day+f'T{hour:02}:00:00+05:30'
def create(c,count=6,start=8,end=10):
 status,data=c.request({'action':'create','title':'QA '+uuid.uuid4().hex,'description':'Automated local integration test record.','station':'TNA','location':'QA section','priority':'Medium','required_crew':count,'start_at':time(start),'end_at':time(end)})
 assert status==200,(status,data)
 created.append(data['id']);return data['id']
def assign(c,id,ids,start=8,end=10):return c.request({'action':'assign','job_id':id,'worker_ids':ids,'start_at':time(start),'end_at':time(end)})
try:
 anon=Client()
 check('Anonymous access has no worker records',anon.request()==(200,{'user':None}))
 check('Anonymous mutation rejected',anon.request({'action':'create'})[0]==401)
 check('Wrong password rejected',anon.request({'action':'login','id':'HEAD-TRK','password':'wrong'})[0]==401)
 head=Client();head.login('HEAD-TRK');status,d=head.request();workers=d['workers']
 check('Track head receives exactly 65 Track workers',status==200 and len(workers)==65 and all(w['department_code']=='TRK' for w in workers))
 ready=[w['worker_id'] for w in workers if w['availability_status']=='Available' and w['shift'].startswith('A') and w['station_code'] in ['TNA','DR','KYN','BSR']]
 check('At least six actual CSV workers match the morning shift',len(ready)>=6)
 ids=ready[:6];unavailable=next(w['worker_id'] for w in workers if w['availability_status']!='Available' and w['station_code'] in ['TNA','DR','KYN','BSR']);night=next(w['worker_id'] for w in workers if w['availability_status']=='Available' and w['shift'].startswith('C') and w['station_code'] in ['TNA','DR','KYN','BSR'])
 worker=Client();worker.login(ids[0]);check('Worker role cannot create a job',worker.request({'action':'create'})[0]==403)
 status,capacity_error=head.request({'action':'create','title':'QA impossible crew','description':'Capacity validation','station':'TNA','location':'QA section','priority':'Medium','required_crew':66,'start_at':time(8),'end_at':time(10)})
 check('Impossible crew capacity rejected before creating a job',status==400 and 'eligible' in capacity_error.get('error',''))
 job=create(head)
 overlap=create(head)
 check('Crew size enforced',assign(head,job,ids[:5])[0]==400)
 check('Duplicate worker IDs rejected',assign(head,job,[ids[0]]*6)[0]==400)
 check('Unavailable worker rejected',assign(head,job,ids[:5]+[unavailable])[0]==409)
 check('Worker outside their shift rejected',assign(head,job,ids[:5]+[night])[0]==409)
 signal=Client();signal.login('HEAD-SIG');_,signaldata=signal.request();foreign=signaldata['workers'][0]['worker_id']
 check('Cross-department worker rejected',assign(head,job,ids[:5]+[foreign])[0]==403)
 check('Another head cannot assign a Track job',assign(signal,job,ids)[0]==404)
 check('Six manually selected workers assigned',assign(head,job,ids)[0]==200)
 _,d=head.request();saved=next(j for j in d['jobs'] if j['id']==job)
 check('Saved crew is exactly the selected six workers',saved['crew_count']==6 and {x['worker_id'] for x in saved['crew']}==set(ids))
 for id in ids:
  w=Client();w.login(id);_,wd=w.request();matches=[j for j in wd['jobs'] if j['id']==job]
  check(f'{id} sees assigned job and IST-equivalent time',len(matches)==1 and matches[0]['start_at']==day+'T02:30:00.000Z')
 outsider=Client();outsider.login(next(w['worker_id'] for w in workers if w['worker_id'] not in ids));_,out=outsider.request()
 check('Unselected worker cannot see this job',not any(j['id']==job for j in out['jobs']) and 'workers' not in out)
 check('Unselected worker cannot acknowledge another worker job',outsider.request({'action':'acknowledge','job_id':job})[0]==404)
 check('Assigned worker can acknowledge the job',worker.request({'action':'acknowledge','job_id':job})[0]==200)
 _,d=head.request();j=next(j for j in d['jobs'] if j['id']==job)
 check('Head sees persisted acknowledgement',next(c for c in j['crew'] if c['worker_id']==ids[0])['status']=='Acknowledged')
 check('Overlapping assignment rejected',assign(head,overlap,ids)[0]==409)
 _,d=head.request();j=next(j for j in d['jobs'] if j['id']==overlap)
 check('Failed assignment rolls back job and crew together',j['status']=='Pending' and j['crew_count']==0)
 adjacent=create(head,start=10,end=12)
 check('Adjacent non-overlapping booking allowed',assign(head,adjacent,ids,10,12)[0]==200)
 check('Already-assigned job cannot be assigned again',assign(head,job,ids)[0]==409)
 race1=create(head,count=1,start=12,end=13);race2=create(head,count=1,start=12,end=13)
 head2=Client();head2.login('HEAD-TRK')
 with concurrent.futures.ThreadPoolExecutor() as ex:
  a=ex.submit(assign,head,race1,[ids[0]],12,13);b=ex.submit(assign,head2,race2,[ids[0]],12,13);statuses=sorted([a.result()[0],b.result()[0]])
 check('Concurrent conflicting jobs allow only one allocation',statuses==[200,409])
 same=create(head,count=1,start=13,end=14)
 with concurrent.futures.ThreadPoolExecutor() as ex:
  a=ex.submit(assign,head,same,[ids[1]],13,14);b=ex.submit(assign,head2,same,[ids[2]],13,14);statuses=sorted([a.result()[0],b.result()[0]])
 check('Concurrent allocation of one job cannot exceed required crew',statuses==[200,409])
 check('Logout invalidates session',worker.request({'action':'logout'})[0]==200 and worker.request()==(200,{'user':None}))
 print(f'\n{len(checks)} integration checks passed.')
finally:
 # Test IDs are generated and recorded by this process; preserve all other user work.
 for p in (ROOT/'.wrangler/state/v3/d1/miniflare-D1DatabaseObject').glob('*.sqlite'):
  con=sqlite3.connect(p)
  if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
   for id in created:
    con.execute('DELETE FROM assignments WHERE job_id=?',(id,));con.execute('DELETE FROM jobs WHERE id=? AND title LIKE ?', (id,'QA %'))
   con.commit();print(f'Cleaned {len(created)} test jobs; existing work preserved.')
  con.close()
