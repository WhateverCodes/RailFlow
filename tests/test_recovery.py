import copy,unittest
from railflow.domain import base_state,mutate,train_input
from railflow.engine import schedule
from railflow.validator import validate

AUTH=dict(role='authority',name='Authority',username='AUTHORITY',station=None)
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.s=base_state()
        self.s['trains']=[t for t in self.s['trains'] if t['id']=='REC01']
        self.t=self.s['trains'][0]
        mutate(self.s,AUTH,dict(action='replan'))
    def late(self):
        s=self.t['stops'][0]
        mutate(self.s,AUTH,dict(action='simulate',edits=[dict(train='REC01',stop=0,arrival=s['arrival'],departure=s['departure']+60,reason='Late departure')]))
    def test_hour_late_recovers_in_stages(self):
        self.late();r=self.s['plan']['rows']
        self.assertEqual([(x['delay'],x['departure_delay']) for x in r],[(0,60),(20,15),(5,2),(0,0)])
        self.assertEqual(r[1]['recovered_running'],40);self.assertEqual(r[1]['recovered_dwell'],5)
        self.assertTrue(validate(self.s,self.s['plan'])['passed'])
    def test_incident_applies_once_and_can_recover(self):
        mutate(self.s,AUTH,dict(action='event',event=dict(kind='delay',train='REC01',station=self.t['stops'][0]['station'],minutes=60,reason='Signal problem')))
        self.assertEqual([r['delay'] for r in self.s['plan']['rows']],[60,20,5,0])
    def test_no_recovery_without_allowances(self):
        for s in self.t['stops']:s.pop('min_run',None);s.pop('min_dwell',None)
        self.late();self.assertEqual([r['delay'] for r in self.s['plan']['rows']],[0,60,60,60])
    def test_independent_check_rejects_impossible_speed(self):
        self.late();p=copy.deepcopy(self.s['plan']);p['rows'][1]['arrival']-=1
        self.assertIn('travel',[i['kind'] for i in validate(self.s,p)['issues']])
    def test_independent_check_rejects_short_stop(self):
        self.late();p=copy.deepcopy(self.s['plan']);p['rows'][1]['departure']-=1
        self.assertIn('dwell',[i['kind'] for i in validate(self.s,p)['issues']])
    def test_closure_restricts_recovery(self):
        self.late();s=self.t['stops'][1];s['required_platform']=1
        self.s['events']=[dict(id='C',kind='closure',station=s['station'],platform=1,start=630,end=700,reason='Closed')]
        p=schedule(self.s);self.assertGreaterEqual(p['rows'][1]['arrival'],700);self.assertTrue(validate(self.s,p)['passed'])
    def test_import_preserves_minimums_and_rejects_invalid_values(self):
        self.assertEqual(train_input(self.s,self.t)['stops'][1]['min_run'],15)
        t=copy.deepcopy(self.t);t['stops'][1]['min_run']=100
        with self.assertRaises(ValueError):train_input(self.s,t)
        t=copy.deepcopy(self.t);t['stops'][1]['min_dwell']=0
        with self.assertRaises(ValueError):train_input(self.s,t)
    def test_dataset_is_varied_and_valid(self):
        s=base_state();self.assertTrue(s['plan']['validation']['passed']);self.assertFalse(s['plan']['unscheduled'])
        self.assertGreater(len({t['stops'][0]['arrival'] for t in s['trains']}),20)
        self.assertGreater(len({r['departure']-r['arrival'] for t in s['trains'] for r in t['stops']}),5)

if __name__=='__main__':unittest.main()
