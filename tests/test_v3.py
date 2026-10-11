import copy,unittest
from datetime import date,timedelta
from railflow.domain import base_state,mutate,public_state
from railflow.validator import validate

AUTH=dict(role='authority',name='Authority',username='AUTHORITY',station=None)
def master(sid):return dict(role='master',name='Master',username='SM-'+sid,station=sid)

class RevisionTests(unittest.TestCase):
    def setUp(self):self.s=base_state()
    def edit(self,tid,idx,a,b,p=None):
        stop=next(t for t in self.s['trains'] if t['id']==tid)['stops'][idx]
        mutate(self.s,master(stop['station']),dict(action='simulate',edits=[dict(train=tid,stop=idx,arrival=a,departure=b,required_platform=p,reason='Manual timing revision')]))
    def test_departure_only_change_is_recorded_and_propagates(self):
        t=self.s['trains'][0];r=next(r for r in self.s['plan']['rows'] if r['train']==t['id'] and r['stop']==0)
        self.edit(t['id'],0,r['arrival'],r['departure']+15)
        changed=self.s['last_changes'];first=next(c for c in changed if c['train']==t['id'] and c['after']['stop']==0)
        self.assertEqual(first['before']['arrival'],first['after']['arrival'])
        self.assertEqual(first['after']['departure']-first['before']['departure'],15)
        self.assertTrue(any(c['train']==t['id'] and c['after']['stop']>0 and c['after']['arrival']>c['before']['arrival'] for c in changed))
        visible=public_state(self.s,master(r['station']))
        self.assertTrue(any(c['station']!=r['station'] and c['train']==t['id'] for c in visible['last_changes']))
        self.assertTrue(self.s['edit_outcomes'][0]['exact'])
    def test_explicit_early_departure_and_independent_check(self):
        t=self.s['trains'][0];s=t['stops'][0]
        self.edit(t['id'],0,s['arrival']-10,s['departure']-10)
        row=next(r for r in self.s['plan']['rows'] if r['train']==t['id'] and r['stop']==0)
        self.assertEqual(row['departure_delay'],-10);self.assertTrue(validate(self.s,self.s['plan'])['passed'])
        p=copy.deepcopy(self.s['plan']);p['rows'][0]['departure']=p['rows'][0]['arrival']+1
        self.assertFalse(validate(self.s,p)['passed'])
    def test_unmet_requested_time_explained(self):
        t=self.s['trains'][0];s=t['stops'][0]
        self.edit(t['id'],0,s['arrival'],s['arrival']+1)
        self.assertFalse(self.s['edit_outcomes'][0]['exact']);self.assertIn('dwell',self.s['edit_outcomes'][0]['explanation'])
    def test_overlap_conflict_logged_only_after_actual_replan(self):
        mutate(self.s,AUTH,dict(action='scenario',mode='test'))
        self.edit('T02',0,480,489,1)
        self.assertTrue(any(c['kind']=='overlap' and c['platform']==1 for c in self.s['conflict_history']))
        self.assertTrue(validate(self.s,self.s['plan'])['passed'])
        self.assertEqual(public_state(self.s,dict(role='customer'))['conflict_history'],[])
    def test_operating_dates_include_midnight_rollover(self):
        mutate(self.s,AUTH,dict(action='service_date',service_date='2026-12-31'))
        self.s['trains']=[dict(id='N',name='Night',stops=[dict(station='PUNE',arrival=1435,departure=1445,required_platform=1)])]
        mutate(self.s,AUTH,dict(action='replan'))
        r=self.s['plan']['rows'][0];self.assertEqual(r['arrival_date'],'2026-12-31');self.assertEqual(r['departure_date'],'2027-01-01')
    def test_refusal_reason_alternative_and_atomic_crew_approval(self):
        body=dict(action='job',station='PUNE',platform=4,start=700,end=730,title='Inspect',department='Track',crew_required=2)
        mutate(self.s,AUTH,body);j=self.s['jobs'][0]
        with self.assertRaises(ValueError):mutate(copy.deepcopy(self.s),master('PUNE'),dict(action='job_status',id=j['id'],status='Refused',reason=''))
        mutate(self.s,master('PUNE'),dict(action='job_status',id=j['id'],status='Refused',reason='Crew unavailable',proposed_start='2026-10-13T10:00',proposed_end='2026-10-13T11:00'))
        self.assertEqual(j['alternative']['start'],'2026-10-13T10:00')
        mutate(self.s,AUTH,body);j=self.s['jobs'][-1]
        crew=[w['id'] for w in self.s['workers'] if w['station']=='PUNE' and w['department']=='Track'][:2]
        mutate(self.s,master('PUNE'),dict(action='job_status',id=j['id'],status='Assigned',reason='Approved with crew',crew=crew))
        self.assertEqual(j['status'],'Assigned');self.assertEqual(j['crew'],crew)

if __name__=='__main__':unittest.main()
