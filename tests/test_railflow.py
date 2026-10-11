import copy,unittest,random
from railflow.domain import base_state,mutate,public_state
from railflow.engine import schedule,plan_maintenance
from railflow.validator import validate
from railflow.language import interpret

AUTH=dict(role='authority',name='Authority',username='AUTHORITY',station=None)
def master(sid='DEMO'):return dict(role='master',name='Station master',username='SM-'+sid,station=sid)
class RailFlowTests(unittest.TestCase):
    def setUp(self):
        self.s=base_state();mutate(self.s,AUTH,dict(action='scenario',mode='test'))
    def event(self,**data):return mutate(self.s,AUTH,dict(action='event',event=data))
    def test_district_valid_and_all_stations_served(self):
        s=base_state();self.assertTrue(s['plan']['validation']['passed']);self.assertFalse(s['plan']['unscheduled'])
        self.assertEqual({s['id'] for s in s['stations'] if s['id']!='DEMO'},{r['station'] for r in s['plan']['rows']})
    def test_gaps_and_required_platforms(self):
        self.assertTrue(validate(self.s,self.s['plan'])['passed'])
        self.assertEqual(next(r for r in self.s['plan']['rows'] if r['train']=='T01')['platform'],1)
        rows=sorted([r for r in self.s['plan']['rows'] if r['platform']==1],key=lambda r:r['arrival'])
        self.assertTrue(all(b['arrival']-a['departure']>=5 for a,b in zip(rows,rows[1:])))
    def test_delay_and_closure_replan_with_reasons(self):
        self.event(kind='delay',train='T01',station='DEMO',minutes=20,reason='Signal issue')
        r=next(r for r in self.s['plan']['rows'] if r['train']=='T01');self.assertGreaterEqual(r['arrival'],500)
        self.event(kind='closure',station='DEMO',platform=1,start=480,end=540,reason='Inspection')
        self.assertTrue(self.s['plan']['validation']['passed']);self.assertTrue(self.s['last_changes']);self.assertTrue(self.s['before_validation']['issues'])
    def test_early_arrival_no_early_departure(self):
        self.event(kind='early',train='T01',station='DEMO',minutes=10,reason='Ahead of schedule')
        r=next(r for r in self.s['plan']['rows'] if r['train']=='T01');self.assertEqual(r['arrival'],470);self.assertGreaterEqual(r['departure'],489)
    def test_independent_validator_rejects_bad_required_and_gap(self):
        p=copy.deepcopy(self.s['plan']);p['rows'][0]['platform']=2;self.assertFalse(validate(self.s,p)['passed'])
        p=copy.deepcopy(self.s['plan']);a=p['rows'][0];b=p['rows'][1];b.update(station=a['station'],platform=a['platform'],arrival=a['arrival'],departure=a['departure'])
        self.assertTrue(any(i['kind']=='overlap' for i in validate(self.s,p)['issues']))
    def test_infeasible_not_silently_dropped(self):
        for p in range(1,4):self.event(kind='closure',station='DEMO',platform=p,start=0,end=2880,reason='Closed')
        self.assertEqual(len(self.s['plan']['unscheduled']),8);self.assertFalse(self.s['plan']['validation']['complete'])
        broken=copy.deepcopy(self.s['plan']);broken['unscheduled']=[];self.assertFalse(validate(self.s,broken)['passed'])
    def test_validator_reports_nested_overlaps_by_every_pair(self):
        p=copy.deepcopy(self.s['plan'])
        for row,a,b in zip(p['rows'][:3],[480,490,510],[560,495,520]):
            row.update(platform=1,arrival=a,departure=b)
        issues=validate(self.s,p)['issues']
        first,second,third=[r['train'] for r in p['rows'][:3]]
        pairs={(i['other'],i['train']) for i in issues if i['kind']=='overlap'}
        self.assertIn((first,second),pairs);self.assertIn((first,third),pairs)
    def test_station_and_customer_permissions(self):
        for u in [master('PUNE'),dict(role='customer')]:
            with self.assertRaises(PermissionError):mutate(self.s,u,dict(action='settings',station='DEMO',platforms=3,gap=5))
        with self.assertRaises(PermissionError):mutate(self.s,master(),dict(action='train',train={}))
        customer=public_state(self.s,dict(role='customer'));self.assertFalse(customer['workers']);self.assertFalse(customer['jobs'])
    def test_maintenance_accept_assign_and_crew_conflicts(self):
        body=dict(action='job',station='DEMO',platform=2,start=600,end=630,title='Inspect',department='Track',crew_required=2)
        mutate(self.s,AUTH,body);j=self.s['jobs'][0]
        mutate(self.s,master(),dict(action='job_status',id=j['id'],status='Accepted',reason='Reviewed'))
        crew=[w['id'] for w in self.s['workers'] if w['station']=='DEMO' and w['department']=='Track'][:2]
        mutate(self.s,master(),dict(action='job_status',id=j['id'],status='Assigned',reason='Roster checked',crew=crew))
        mutate(self.s,AUTH,{**body,'platform':3});k=self.s['jobs'][1]
        mutate(self.s,master(),dict(action='job_status',id=k['id'],status='Accepted',reason='Reviewed'))
        with self.assertRaises(ValueError):mutate(self.s,master(),dict(action='job_status',id=k['id'],status='Assigned',reason='Duplicate crew',crew=crew))
        mutate(self.s,master(),dict(action='job_status',id=j['id'],status='In progress',reason='Start reported by station master'))
        mutate(self.s,master(),dict(action='job_status',id=j['id'],status='Completed',reason='Checked complete'))
    def test_rejected_job_does_not_block_and_safe_window(self):
        mutate(self.s,AUTH,dict(action='job',station='DEMO',platform=1,start=480,end=550,title='Inspect',department='Track',crew_required=2))
        old=copy.deepcopy(self.s['plan']['rows']);j=self.s['jobs'][0]
        mutate(self.s,master(),dict(action='job_status',id=j['id'],status='Refused',reason='Resources unavailable'))
        self.assertEqual(old,self.s['plan']['rows'])
        window=plan_maintenance(self.s,'DEMO',1,480,900,30);self.assertIsNotNone(window)
        for r in self.s['plan']['rows']:
            if r['platform']==1:self.assertFalse(window['start']<r['departure']+5 and window['end']>r['arrival']-5)
    def test_local_ai_and_missing_slots(self):
        x=interpret('Delay T01 at DEMO by 20 minutes',self.s);self.assertEqual(x['draft']['kind'],'delay');self.assertEqual(x['draft']['minutes'],20);self.assertFalse(x['missing'])
        x=interpret('Close platform 2 at DEMO from 08:00 to 09:00',self.s);self.assertEqual(x['draft']['kind'],'closure');self.assertEqual(x['draft']['end'],540)
        self.assertTrue(interpret('There is a problem',self.s)['missing'])
    def test_onward_delay_propagation_and_overnight(self):
        self.s['events']=[];self.s['trains']=[dict(id='NIGHT',name='Night train',stops=[dict(station='DEMO',arrival=1430,departure=1435,required_platform=1),dict(station='PUNE',arrival=1460,departure=1465,required_platform=None)])]
        self.event(kind='delay',train='NIGHT',station='DEMO',minutes=30,reason='Signal')
        a,b=self.s['plan']['rows'];self.assertGreaterEqual(b['arrival'],a['departure']+25);self.assertTrue(validate(self.s,self.s['plan'])['passed'])
    def test_fuzz_closures_always_valid_or_explicit_unscheduled(self):
        random.seed(5)
        for i in range(30):
            s=copy.deepcopy(self.s);s['events']=[dict(id=str(i),kind='closure',station='DEMO',platform=random.randint(1,3),start=470+i,end=550+i,reason='Test')]
            p=schedule(s);self.assertTrue(validate(s,p)['passed'])
    def test_editable_simulation_preserves_advertised_times_and_reports_delay(self):
        mutate(self.s,master(),dict(action='simulate',edits=[dict(train='T01',stop=0,arrival=505,departure=514,required_platform=1,reason='Signal inspection')]))
        row=next(r for r in self.s['plan']['rows'] if r['train']=='T01')
        self.assertEqual(row['scheduled_arrival'],480);self.assertGreaterEqual(row['arrival'],505);self.assertGreater(row['delay'],0)
        self.assertIn('Approach',row['path']);self.assertIn('Signal inspection',row['reason'])
        p=copy.deepcopy(self.s['plan']);r=next(r for r in p['rows'] if r['train']=='T01');r.update(arrival=480,departure=489)
        self.assertFalse(validate(self.s,p)['passed'])
    def test_simulation_edits_respect_station_scope(self):
        with self.assertRaises(PermissionError):
            mutate(self.s,master('PUNE'),dict(action='simulate',edits=[dict(train='T01',stop=0,arrival=500,departure=510,required_platform=1,reason='Not my station')]))
    def test_simulation_does_not_apply_existing_delay_twice(self):
        self.event(kind='delay',train='T01',station='DEMO',minutes=20,reason='Signal issue')
        row=next(r for r in self.s['plan']['rows'] if r['train']=='T01')
        mutate(self.s,master(),dict(action='simulate',edits=[dict(train='T01',stop=0,arrival=row['arrival'],departure=row['departure'],required_platform=3,reason='Change platform')]))
        revised=next(r for r in self.s['plan']['rows'] if r['train']=='T01')
        self.assertEqual(revised['arrival'],row['arrival']);self.assertEqual(revised['platform'],3)
        self.assertTrue(validate(self.s,self.s['plan'])['passed'])
    def test_platform_changes_have_explanation(self):
        self.event(kind='closure',station='DEMO',platform=2,start=470,end=600,reason='Inspection')
        for c in self.s['last_changes']:
            if c['before'] and c['after'] and c['before']['platform']!=c['after']['platform']:
                self.assertNotEqual(c['reason'],'On schedule')

if __name__=='__main__':unittest.main()
