"""RailFlow local server. Python standard library only; no installation step."""
import argparse,hashlib,hmac,json,mimetypes,secrets,sqlite3,time,threading,os
from datetime import datetime,timezone
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse,parse_qs,quote
from contextlib import contextmanager
from railflow.domain import base_state,mutate,public_state,station,scope,integer,authority,recalculate,district_trains
from railflow.engine import plan_maintenance
from railflow.validator import validate
from railflow.language import interpret
from railflow.reports import dataset,csv_bytes,pdf_bytes

ROOT=Path(__file__).resolve().parent
LOCK=threading.RLock();SESSIONS={};ATTEMPTS={}
DB=Path(os.environ.get('RAILFLOW_DATA_DIR',str(ROOT/'local-data')))/'railflow.sqlite3'
SALT=b'RailFlow demo password v1'
PASSWORD=hashlib.pbkdf2_hmac('sha256',os.environ.get('RAILFLOW_PASSWORD','RailFlow@123').encode(),SALT,120000)
@contextmanager
def connection():
    db=sqlite3.connect(DB)
    try:
        with db:yield db
    finally:db.close()
def initialize():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS history(revision INTEGER PRIMARY KEY, timestamp TEXT, actor TEXT, note TEXT, snapshot TEXT NOT NULL)')
        if not db.execute('SELECT 1 FROM state').fetchone():
            s=base_state();js=json.dumps(s);db.execute('INSERT INTO state VALUES(1,?)',(js,));db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(1,datetime.now(timezone.utc).isoformat(),'System','Initial fictional timetable',js))
        else:
            s=json.loads(db.execute('SELECT value FROM state WHERE id=1').fetchone()[0])
            if s.get('schema_version',1)<4:
                if s.get('mode')=='district':
                    seeds=district_trains(s['stations']);ids={t['id'] for t in seeds}
                    s['trains']=seeds+[t for t in s['trains'] if t['id'] not in ids]
                recalculate(s,s.get('plan'));s['schema_version']=4;s['revision']+=1;js=json.dumps(s)
                db.execute('UPDATE state SET value=? WHERE id=1',(js,));db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(s['revision'],datetime.now(timezone.utc).isoformat(),'System','Varied fictional timetable with minimum travel, stop times and recovery allowances; prior revisions retained',js))
def load():
    with connection() as db:return json.loads(db.execute('SELECT value FROM state WHERE id=1').fetchone()[0])
def account(username,state):
    if username=='AUTHORITY':return dict(role='authority',name='Pune city authority',station=None,username=username)
    if username=='CUSTOMER':return dict(role='customer',name='Passenger',station=None,username=username)
    if username.startswith('SM-'):
        st=station(state,username[3:]);return dict(role='master',name=st['name']+' station master',station=st['id'],username=username)
    raise ValueError('Unknown demo account.')

def history_records(user,limit=40):
    with connection() as db:
        query='SELECT revision,timestamp,actor,note,snapshot FROM history ORDER BY revision DESC'
        rows=db.execute(query+' LIMIT ?',(limit,)).fetchall() if limit is not None else db.execute(query).fetchall()
    u=user
    result=[]
    for revision,stamp,actor,note,snapshot in rows:
        s=json.loads(snapshot)
        if u['role']=='master':
            affected={c['train'] for c in s.get('last_changes',[]) if c['station']==u['station']}
            edits=[c for c in s.get('last_changes',[]) if c['station']==u['station'] or c['train'] in affected]
            result.append(dict(revision=revision,timestamp=stamp,actor=actor,note=f'{len(edits)} schedule changes at your station',changes=edits,validation=s['plan']['validation'],service_date=s.get('service_date',stamp[:10])))
        else:result.append(dict(revision=revision,timestamp=stamp,actor=actor,note=note,changes=s.get('last_changes',[]),validation=s['plan']['validation'],service_date=s.get('service_date',stamp[:10])))
    return result

class Handler(BaseHTTPRequestHandler):
    server_version='RailFlow/1.0'
    def send(self,status,data,cookie=None):
        payload=json.dumps(data,ensure_ascii=False).encode();self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store')
        if cookie:self.send_header('Set-Cookie',cookie)
        self.end_headers();self.wfile.write(payload)
    def user(self):
        c=SimpleCookie();c.load(self.headers.get('Cookie',''));token=c.get('railflow_session');session=SESSIONS.get(token.value if token else '')
        if not session or session['expires']<time.time():raise PermissionError('Please sign in again.')
        return session['user']
    def do_GET(self):
        try:
            path=urlparse(self.path).path
            if path=='/api/health':return self.send(200,{'ok':True})
            if path=='/api/stations':
                return self.send(200,{'stations':[{k:s[k] for k in ('id','name','corridor')} for s in load()['stations']]})
            if path=='/api/state':
                u=self.user();return self.send(200,dict(user=u,state=public_state(load(),u)))
            if path=='/api/history':
                u=self.user()
                if u['role']=='customer':raise PermissionError('History is restricted to operating roles.')
                return self.send(200,{'history':history_records(u)})
            if path=='/api/download':
                u=self.user();params=parse_qs(urlparse(self.path).query)
                kind=params.get('dataset',['timetable'])[0];fmt=params.get('format',['csv'])[0]
                if fmt not in ('csv','pdf'):raise ValueError('Choose CSV or PDF format.')
                with LOCK:
                    current=load()
                    if params.get('revision') and params['revision'][0]!=str(current['revision']):
                        return self.send(409,{'error':'The official revision changed. Refresh before exporting.'})
                    records=history_records(u,None) if kind=='history' and u['role']!='customer' else []
                    public=public_state(current,u)
                sid=params.get('station',[''])[0] or None
                headers,rows=dataset(public,u,kind,records,sid,params.get('search',[''])[0])
                titles={'timetable':'RailFlow - Timetable','history':'RailFlow - Revision history','backlog':'RailFlow - Backlog report','disruptions':'RailFlow - Disruption report'}
                raw=csv_bytes(headers,rows) if fmt=='csv' else pdf_bytes(titles[kind],headers,rows,public,u)
                name=f"railflow-{kind}-{sid or (u['station'] if u['role']=='master' else 'all')}-{current['service_date']}-r{current['revision']}.{fmt}"
                self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8' if fmt=='csv' else 'application/pdf')
                self.send_header('Content-Disposition',f"attachment; filename={name}; filename*=UTF-8''{quote(name)}")
                self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers();self.wfile.write(raw);return
            if path=='/api/export':
                u=self.user();return self.send(200,public_state(load(),u))
            if path=='/api/timetable':
                self.user();return self.send(200,load()['trains'])
            file=ROOT/'static'/('index.html' if path=='/' else path.lstrip('/'))
            if not file.resolve().is_relative_to((ROOT/'static').resolve()) or not file.is_file():return self.send(404,{'error':'Not found'})
            raw=file.read_bytes();self.send_response(200);mime={'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png'}.get(file.suffix.lower(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream');self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-cache')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        except PermissionError as e:self.send(403,{'error':str(e)})
        except Exception as e:self.send(400,{'error':str(e)})
    def do_POST(self):
        try:
            if self.headers.get('X-RailFlow')!='1':raise PermissionError('Missing request verification header.')
            origin=self.headers.get('Origin')
            if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise PermissionError('Cross-site requests are not allowed.')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=1000000:raise ValueError('Request must be smaller than 1 MB.')
            body=json.loads(self.rfile.read(size));path=urlparse(self.path).path
            if not isinstance(body,dict):raise ValueError('Request must be an object.')
            if path=='/api/login':
                ip=self.client_address[0];recent=[t for t in ATTEMPTS.get(ip,[]) if t>time.time()-60]
                if len(recent)>=12:raise ValueError('Too many login attempts. Wait a minute.')
                recent.append(time.time());ATTEMPTS[ip]=recent
                candidate=hashlib.pbkdf2_hmac('sha256',str(body.get('password','')).encode(),SALT,120000)
                if not hmac.compare_digest(candidate,PASSWORD):raise PermissionError('Incorrect demo password.')
                u=account(str(body.get('username','')).upper(),load());token=secrets.token_urlsafe(32)
                SESSIONS[token]={'user':u,'expires':time.time()+43200}
                return self.send(200,{'user':u},f'railflow_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
            u=self.user()
            if path=='/api/logout':
                c=SimpleCookie();c.load(self.headers.get('Cookie',''));SESSIONS.pop(c['railflow_session'].value,None)
                return self.send(200,{'ok':True},'railflow_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if path=='/api/interpret':
                if u['role']=='customer':raise PermissionError('Customers cannot enter disruptions.')
                return self.send(200,interpret(body.get('text',''),load()))
            if path=='/api/window':
                authority(u);s=load();st=station(s,body.get('station'))
                platform=integer(body.get('platform'),1,st['platforms'],'Platform');a=integer(body.get('start'),0,2879,'Earliest start');b=integer(body.get('end'),a+1,2880,'Latest end');duration=integer(body.get('duration'),5,480,'Work duration')
                return self.send(200,{'window':plan_maintenance(s,st['id'],platform,a,b,duration),'revision':s['revision']})
            if path in ('/api/change','/api/preview'):
                with LOCK:
                    s=load()
                    if body.get('revision')!=s['revision']:return self.send(409,{'error':'Another user changed the plan. Refresh before trying again.'})
                    note=mutate(s,u,body)
                    if path=='/api/change':
                        if not s['plan']['validation']['complete']:raise ValueError('This draft has unscheduled calls. Resolve them before publishing an official schedule.')
                        js=json.dumps(s,ensure_ascii=False)
                        with connection() as db:
                            db.execute('UPDATE state SET value=? WHERE id=1',(js,));db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(s['revision'],datetime.now(timezone.utc).isoformat(),u['username'],note,js))
                    return self.send(200,{'state':public_state(s,u),'note':note,'preview':path.endswith('preview')})
            if path=='/api/validate':
                if u['role']=='customer':raise PermissionError('Operating role required.')
                s=load();return self.send(200,validate(s,body.get('plan',s['plan'])))
            self.send(404,{'error':'Unknown endpoint'})
        except PermissionError as e:self.send(403,{'error':str(e)})
        except (ValueError,TypeError,KeyError) as e:self.send(400,{'error':str(e)})
        except Exception as e:
            print('Server error:',repr(e));self.send(500,{'error':'Request failed. No revision was saved.'})
    def log_message(self,fmt,*args):
        if '/api/state' not in str(args):print(self.log_date_time_string(),fmt%args)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=3010);args=parser.parse_args()
    initialize();server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'RailFlow READY at http://127.0.0.1:{args.port}',flush=True)
    print('Demo password: RailFlow@123 (unless RAILFLOW_PASSWORD is set). Keep this window open.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:print('\nStopped.')
    finally:server.server_close()
