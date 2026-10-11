import copy
import unittest
from scenario import build_scenario
from engine import compatible, generate, validate, normalized_config, SETUP


class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build_scenario()
        cls.config = dict(horizon=7, start_date='2026-09-08', incidents=[])
        cls.plan = generate(cls.data, cls.config)

    def test_source_counts_and_graph_integrity(self):
        d = self.data
        for key, count in [('stations',20),('sections',19),('assets',570),('tasks',500),('defects',100),('services',8400)]:
            self.assertEqual(len(d[key]), count, key)
        self.assertEqual(len({t['id'] for t in d['tasks']}),500)
        self.assertEqual(sum(s['kind']=='Passenger' for s in d['services']),6000)
        self.assertEqual(sum(s['kind']=='Freight' for s in d['services']),2400)
        self.assertTrue(all(t['asset_id'] in {a['id'] for a in d['assets']} for t in d['tasks']))
        self.assertTrue(all(a['risk']['7']<=a['risk']['30']<=a['risk']['90'] for a in d['assets']))

    def test_both_schedules_and_comparison(self):
        p = self.plan
        self.assertGreater(len(p['blocks']),0)
        self.assertGreater(p['metrics']['joint_blocks'],0)
        self.assertEqual(validate(self.data,p),[])
        self.assertEqual(validate(self.data,dict(config=p['config'],blocks=p['baseline']['blocks_detail'])),[])
        self.assertLessEqual(p['metrics']['utilization'],100)
        self.assertGreater(p['comparison']['tasks'],0)
        self.assertGreater(p['comparison']['minutes_saved'],0)
        scheduled = {t for b in p['blocks'] for t in b['tasks']}
        deferred = {t['id'] for t in p['unscheduled']}
        eligible = {t['id'] for t in self.data['tasks'] if t['release_day']<7}
        self.assertFalse(scheduled & deferred)
        self.assertEqual(scheduled|deferred,eligible)

    def test_incompatible_work_and_temporal_condition(self):
        a = copy.deepcopy(self.data['tasks'][0]);b=copy.deepcopy(a)
        a.update(department='TRK',task_type='Deep screening',due_day=0,dependencies=[],power_required=False,separation_confirmed=True)
        b.update(department='SIG',task_type='Track circuit testing',due_day=0,dependencies=[])
        self.assertFalse(compatible(a,b))
        b.update(department='TRC',task_type='OHE inspection',power_required=True,separation_confirmed=True,due_day=20)
        self.assertFalse(compatible(a,b))
        b.update(due_day=0,separation_confirmed=False)
        self.assertFalse(compatible(a,b))

    def test_validator_rejects_unsafe_manual_edits(self):
        for change in ['duration','duplicate','daytime','power','headway']:
            p=copy.deepcopy(self.plan)
            b=p['blocks'][0]
            if change=='duration':b['duration']+=1
            if change=='duplicate':p['blocks'].append(copy.deepcopy(b))
            if change=='daytime':b.update(start=600,end=600+b['duration'])
            if change=='power':
                b=next(b for b in p['blocks'] if b['power']);b['power']=False
            if change=='headway':
                # The incident begins exactly at block end; its five-minute margin must conflict.
                p['config']['incidents']=[dict(kind='freight',section=b['section'],start=b['end'],end=b['end']+5)]
            self.assertTrue(validate(self.data,p),change)

    def test_overlapping_machine_outages_merge(self):
        config=copy.deepcopy(self.config)
        config['incidents']=[dict(kind='machine',machine='tamper',start=0,end=120),dict(kind='machine',machine='tamper',start=60,end=180)]
        normalized=normalized_config(config,self.data)
        self.assertEqual(len(normalized['incidents']),1)
        self.assertEqual(validate(self.data,dict(config=config,blocks=[])),[])

    def test_disruption_creates_feasible_revision(self):
        p=self.plan;b=p['blocks'][0]
        config=copy.deepcopy(self.config)
        config['incidents']=[dict(kind='freight',section=b['section'],start=b['start'],end=b['end'])]
        revised=generate(self.data,config,p)
        self.assertEqual(validate(self.data,revised),[])
        self.assertTrue(any(c['change'] in ['Moved','Deferred'] for c in revised['changes'] if c['task_id'] in b['tasks']))
        self.assertTrue(any(c['change']=='Retained' for c in revised['changes']))

    def test_monthly_horizon(self):
        p=generate(self.data,dict(horizon=30,start_date='2026-09-08',incidents=[]))
        self.assertEqual(validate(self.data,p),[])
        self.assertEqual(len({t for b in p['blocks'] for t in b['tasks']})+len(p['unscheduled']),500)
        self.assertGreater(p['metrics']['tasks'],self.plan['metrics']['tasks'])


if __name__=='__main__':
    unittest.main()
