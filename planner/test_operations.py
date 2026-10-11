import copy
import unittest
from operations import generate, solve, validate


def fixture():
    tasks=[]
    for dep,duration in [('TRK',60),('SIG',30),('TRC',45)]:
        tasks.append(dict(id=dep,department=dep,section_id='PUNE-LNL',line='UP Line',duration=duration,crew=1,
            priority=80,release=360,due=840,machine='',power=False,compatibility_group='inspection',
            compatibility_reference='QA reviewed joint work',nearby=['PUNE','LNL']))
    return dict(tasks=tasks,workers=[dict(id=d,department=d,station='PUNE',ranges=[(360,840)]) for d in ['TRK','SIG','TRC']],
        windows=[dict(section_id='PUNE-LNL',start=360,end=840,power=False,traffic_complete=True)],
        movements=[dict(section_id='PUNE-LNL',start=450,end=480)],existing_blocks=[],setup=10,headway=5,horizon=1,machines={})


class OperationsTests(unittest.TestCase):
    def test_joint_schedule_and_matched_comparison(self):
        data=fixture();p=generate(data)
        self.assertEqual(validate(data,p['blocks']),[])
        self.assertEqual(len(p['blocks']),1)
        self.assertEqual(p['blocks'][0]['duration'],70)
        self.assertEqual(p['comparison']['tasks'],3)
        self.assertEqual(p['comparison']['saved_minutes'],95)

    def test_unknown_traffic_does_not_become_a_work_window(self):
        data=fixture();data['windows']=[];p=generate(data)
        self.assertEqual(p['blocks'],[])
        self.assertEqual(len(p['unscheduled']),3)

    def test_full_duration_deadline_and_power(self):
        data=fixture();data['tasks'][0]['due']=400
        data['tasks'][1]['power']=True
        p=generate(data);self.assertEqual({t for b in p['blocks'] for t in b['tasks']},{'TRC'})

    def test_single_alternative_survives_impossible_bundle(self):
        data=fixture();data['tasks'][0]['duration']=500
        p=generate(data);self.assertEqual({t for b in p['blocks'] for t in b['tasks']},{'SIG','TRC'})

    def test_compatibility_requires_recorded_review(self):
        data=fixture()
        for t in data['tasks']:t['compatibility_reference']=''
        self.assertTrue(all(len(b['tasks'])==1 for b in generate(data)['blocks']))

    def test_nearby_shift_and_machine_capacity(self):
        data=fixture();data['workers'][0]['station']='SUR';data['workers'][1]['ranges']=[(360,380)]
        data['tasks'][2]['machine']='tower';data['machines']={'tower':0}
        self.assertEqual(generate(data)['blocks'],[])

    def test_audit_catches_tampering(self):
        data=fixture();good=solve(data)['blocks']
        for mutate in [lambda b:b.update(start=440,end=510),lambda b:b.update(end=b['end']+1),lambda b:b['crew_witness'].update(TRK=['SIG']),lambda b:b.update(tasks=['TRK','TRK']),lambda b:b.update(section_id='OTHER')]:
            blocks=copy.deepcopy(good);mutate(blocks[0]);self.assertTrue(validate(data,blocks))

    def test_midnight_and_monthly_horizon(self):
        data=fixture();data['horizon']=30
        for t in data['tasks']:t.update(release=1430,due=1600)
        for w in data['workers']:w['ranges']=[(1320,1800)]
        data['windows']=[dict(section_id='PUNE-LNL',start=1430,end=1600,power=False)]
        p=generate(data);self.assertEqual(p['blocks'][0]['start'],1430);self.assertEqual(validate(data,p['blocks']),[])

    def test_replanning_uses_changed_movement(self):
        data=fixture();old=generate(data)['blocks'][0]
        data['movements'].append(dict(section_id='PUNE-LNL',start=old['start'],end=old['end']))
        new=generate(data)['blocks'][0]
        self.assertGreaterEqual(new['start'],old['end']+5)

    def test_released_section_and_worker_overlap(self):
        data=fixture();data['existing_blocks']=[dict(section_id='PUNE-LNL',start=360,end=840,machines={})]
        self.assertEqual(generate(data)['blocks'],[])
        data=fixture();data['tasks'].append({**data['tasks'][0],'id':'TRK2','section_id':'PUNE-DD'})
        data['windows'].append(dict(section_id='PUNE-DD',start=360,end=430,power=False))
        p=generate(data);self.assertEqual(validate(data,p['blocks']),[])
        times=[(b['start'],b['end']) for b in p['blocks'] if any(t.startswith('TRK') for t in b['tasks'])]
        self.assertTrue(len(times)<2 or times[0][1]<=times[1][0])


if __name__=='__main__':unittest.main()
