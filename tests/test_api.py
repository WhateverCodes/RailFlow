import unittest,tempfile,threading,json,urllib.request,urllib.error,http.cookiejar
from pathlib import Path
import server

class ApiTests(unittest.TestCase):
    def setUp(self):
        test_root=Path(__file__).resolve().parents[1]/'.test-data';test_root.mkdir(exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=test_root);server.DB=Path(self.tmp.name)/'test.sqlite3';server.SESSIONS.clear();server.ATTEMPTS.clear();server.initialize()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.url='http://127.0.0.1:'+str(self.http.server_port)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.auth=self.client('AUTHORITY');self.master=self.client('SM-PUNE');self.customer=self.client('CUSTOMER')
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();self.tmp.cleanup()
    def client(self,name):
        op=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.request(op,'/api/login',dict(username=name,password='RailFlow@123'))
        return op
    def request(self,client,path,body=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','X-RailFlow':'1'})
        try:
            with client.open(req) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
    def state(self):return self.request(self.auth,'/api/state')[1]['state']
    def test_preview_is_not_a_write_and_stale_revision_rejected(self):
        s=self.state();cmd=dict(action='event',event=dict(kind='closure',station='PUNE',platform=1,start=480,end=560,reason='Inspection'),revision=s['revision'])
        code,p=self.request(self.auth,'/api/preview',cmd);self.assertEqual(code,200);self.assertEqual(self.state()['revision'],s['revision'])
        self.assertEqual(self.request(self.auth,'/api/change',cmd)[0],200)
        self.assertEqual(self.request(self.auth,'/api/change',cmd)[0],409)
        self.assertEqual(len(self.state()['events']),1)
    def test_customer_cannot_mutate_and_export_is_redacted(self):
        s=self.state();code,_=self.request(self.customer,'/api/change',dict(action='clock',clock=600,revision=s['revision']));self.assertEqual(code,403)
        _,d=self.request(self.customer,'/api/export');self.assertEqual(d['workers'],[]);self.assertEqual(d['jobs'],[]);self.assertEqual(d['events'],[])
        self.assertEqual(self.request(self.customer,'/api/history')[0],403)
    def test_station_scope_and_import_rollback(self):
        s=self.state();code,_=self.request(self.master,'/api/change',dict(action='settings',station='LNL',platforms=1,gap=5,revision=s['revision']));self.assertEqual(code,403)
        code,_=self.request(self.auth,'/api/change',dict(action='import',trains=[{'id':'BAD'}],revision=s['revision']));self.assertEqual(code,400)
        self.assertEqual(self.state(),s)
    def test_maintenance_handoff_and_customer_short_reason(self):
        s=self.state();body=dict(action='job',station='PUNE',platform=1,start=480,end=600,title='Confidential internal inspection notes',department='Signal',crew_required=2,revision=s['revision'])
        self.assertEqual(self.request(self.auth,'/api/change',body)[0],200)
        s=self.state();j=s['jobs'][-1]
        accept=dict(action='job_status',id=j['id'],status='Accepted',reason='Internal review completed',revision=s['revision'])
        self.assertEqual(self.request(self.auth,'/api/change',accept)[0],403)
        self.assertEqual(self.request(self.master,'/api/change',accept)[0],200)
        s=self.state();crew=[w['id'] for w in s['workers'] if w['station']=='PUNE' and w['department']=='Signal'][:2]
        self.assertEqual(self.request(self.master,'/api/change',dict(action='job_status',id=j['id'],status='Assigned',crew=crew,reason='Checked',revision=s['revision']))[0],200)
        _,c=self.request(self.customer,'/api/export');serialized=json.dumps(c)
        self.assertNotIn('Confidential',serialized);self.assertNotIn('Internal review',serialized)
    def test_bad_external_origin_and_no_session(self):
        op=urllib.request.build_opener();self.assertEqual(self.request(op,'/api/state')[0],403)
        req=urllib.request.Request(self.url+'/api/login',data=b'{}',headers={'X-RailFlow':'1','Origin':'https://example.com'})
        with self.assertRaises(urllib.error.HTTPError) as error:op.open(req)
        self.assertEqual(error.exception.code,403)
    def test_independent_validator_rejects_tampered_plan(self):
        s=self.state();p=s['plan'];p['rows'][0]['platform']=999
        code,result=self.request(self.auth,'/api/validate',dict(plan=p));self.assertEqual(code,200);self.assertFalse(result['passed'])
    def test_departure_draft_does_not_change_official_until_published(self):
        s=self.state();t=s['trains'][0];stop=t['stops'][0]
        command=dict(action='simulate',revision=s['revision'],edits=[dict(train=t['id'],stop=0,arrival=stop['arrival'],departure=stop['departure']+10,required_platform=None,reason='Departure edit')])
        code,draft=self.request(self.auth,'/api/preview',command)
        self.assertEqual(code,200);self.assertEqual(self.state(),s)
        self.assertTrue(draft['state']['edit_outcomes'][0]['exact'])
        self.assertEqual(self.request(self.auth,'/api/change',{**command,'publish':True})[0],200)
        actual=next(r for r in self.state()['plan']['rows'] if r['train']==t['id'] and r['stop']==0)
        self.assertEqual(actual['departure'],stop['departure']+10)
    def test_incomplete_draft_cannot_be_published(self):
        s=self.state();t=s['trains'][0];stop=t['stops'][0]
        command=dict(action='simulate',revision=s['revision'],publish=True,edits=[dict(train=t['id'],stop=0,arrival=stop['arrival']+200,departure=stop['departure']+200,required_platform=1,reason='Beyond recovery allowance')])
        code,_=self.request(self.auth,'/api/change',command)
        self.assertEqual(code,400);self.assertEqual(self.state(),s)

    def test_incomplete_change_without_publish_flag_is_rejected(self):
        s=self.state();t=s['trains'][0];stop=t['stops'][0]
        command=dict(action='simulate',revision=s['revision'],edits=[dict(train=t['id'],stop=0,arrival=stop['arrival']+200,departure=stop['departure']+200,required_platform=1,reason='Beyond recovery allowance')])
        code,draft=self.request(self.auth,'/api/preview',command)
        self.assertEqual(code,200)
        self.assertFalse(draft['state']['plan']['validation']['complete'])
        self.assertEqual(self.request(self.auth,'/api/change',command)[0],400)
        self.assertEqual(self.state(),s)

    def test_interpret_preview_confirm_workflow_and_comparison(self):
        s=self.state();t=s['trains'][0];stop=t['stops'][0]
        code,proposal=self.request(self.auth,'/api/interpret',dict(text=f"Delay {t['id']} at {stop['station']} by 10 minutes"))
        self.assertEqual(code,200);self.assertFalse(proposal['clarification_required'])
        self.assertEqual(self.state(),s)
        command=dict(action='event',event=proposal['draft'],revision=s['revision'])
        code,draft=self.request(self.auth,'/api/preview',command)
        self.assertEqual(code,200);self.assertEqual(self.state(),s)
        comparison=draft['state']['strategy_comparison']
        self.assertTrue(comparison['minimum_disruption']['validation'])
        self.assertIn('execution_ms',comparison['baseline'])
        self.assertEqual(self.request(self.auth,'/api/change',{**command,'publish':True})[0],200)
        self.assertEqual(self.state()['revision'],s['revision']+1)
        _,customer=self.request(self.customer,'/api/state')
        self.assertNotIn('strategy_comparison',customer['state'])

    def download_report(self,client,kind,fmt,extra=''):
        request=urllib.request.Request(self.url+f'/api/download?dataset={kind}&format={fmt}'+extra)
        try:
            with client.open(request) as response:return response.status,response.headers,response.read()
        except urllib.error.HTTPError as error:return error.code,error.headers,error.read()

    def test_download_all_three_pdf_reports_and_csv(self):
        for kind in ('history','backlog','disruptions'):
            status,headers,raw=self.download_report(self.auth,kind,'pdf')
            self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'application/pdf')
            self.assertTrue(raw.startswith(b'%PDF-'));self.assertIn('attachment',headers['Content-Disposition'])
        status,headers,raw=self.download_report(self.auth,'timetable','csv')
        self.assertEqual(status,200);self.assertEqual(len(raw.decode('utf-8-sig').splitlines()),len(self.state()['plan']['rows'])+1)

    def test_download_reports_preserve_permissions_and_station_scope(self):
        import csv,io
        for kind in ('history','backlog','disruptions'):
            self.assertEqual(self.download_report(self.customer,kind,'pdf')[0],403)
        code,_,raw=self.download_report(self.master,'timetable','csv')
        self.assertEqual(code,200)
        records=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertTrue(records);self.assertTrue(all(r['station']=='PUNE' for r in records))
        self.assertEqual(self.download_report(self.master,'timetable','csv','&station=LNL')[0],403)
        self.assertEqual(self.download_report(self.master,'timetable','csv','&station=DEMO')[0],403)
        self.assertEqual(self.download_report(self.auth,'timetable','csv','&revision=9999')[0],409)

    def test_history_download_includes_beyond_display_limit(self):
        s=self.state()
        with server.connection() as db:
            for revision in range(2,46):
                db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(revision,'2026-10-11T12:00:00Z','AUTHORITY','Stored revision',json.dumps(s)))
        self.assertEqual(len(self.request(self.auth,'/api/history')[1]['history']),40)
        code,_,raw=self.download_report(self.auth,'history','csv')
        self.assertEqual(code,200)
        import csv,io
        self.assertEqual(len(list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))),45)

    def test_validator_rejection_cannot_save_official_revision(self):
        from unittest.mock import patch
        s=self.state()
        rejection=dict(passed=False,complete=False,issues=[dict(message='Deliberately rejected constraint')])
        with patch('railflow.domain.validate',return_value=rejection):
            code,_=self.request(self.auth,'/api/change',dict(action='replan',revision=s['revision'],publish=True))
        self.assertEqual(code,400);self.assertEqual(self.state(),s)

if __name__=='__main__':unittest.main()
