import copy
import random
import unittest
from railflow.engine import schedule
from railflow.strategies import compare_strategies, metrics
from railflow.validator import validate
from railflow.language import interpret


def small():
    def train(tid, a, b, required=None):
        return dict(id=tid, name=tid, stops=[dict(station='S', arrival=a,
                    departure=b, required_platform=required)])
    return dict(stations=[dict(id='S', name='Rivergate', platforms=2, gap=5)],
                trains=[train('A', 480, 500), train('B', 480, 490, 1)],
                events=[], jobs=[], max_delay=120)


class ImprovementTests(unittest.TestCase):
    def test_search_improves_required_platform_contention(self):
        state=small(); before=copy.deepcopy(state)
        plan, comparison=compare_strategies(state)
        self.assertEqual(state,before)
        self.assertTrue(validate(state,plan)['passed'])
        self.assertLess(comparison['minimum_disruption']['total_delay'],comparison['baseline']['total_delay'])
        self.assertEqual(comparison['selected'],'minimum_disruption')
        self.assertEqual(comparison['minimum_disruption']['total_delay'],0)

    def test_retain_previous_platform_without_delay(self):
        state=small(); state['trains']=state['trains'][:1]
        old=schedule(state); old['rows'][0]['platform']=2
        untouched=copy.deepcopy(old)
        plan,c=compare_strategies(state,old)
        self.assertEqual(old,untouched)
        self.assertEqual(plan['rows'][0]['platform'],2)
        self.assertEqual(c['minimum_disruption']['platform_changes'],0)
        self.assertEqual(c['baseline']['platform_changes'],1)

    def test_metrics_account_departure_delay_and_unscheduled(self):
        plan=schedule(small()); old=copy.deepcopy(plan)
        plan['rows'][0]['departure']+=7
        plan['rows'][0]['platform']=2
        plan['unscheduled'].append(dict(train='X',stop=0))
        m=metrics(plan,old)
        self.assertEqual(m['total_delay'],32)
        self.assertEqual(m['maximum_delay'],25)
        self.assertEqual(m['platform_changes'],1)
        self.assertEqual(m['unscheduled'],1)
        self.assertEqual(m['additional_delay'],7)
        self.assertEqual(m['changed_calls'],1)
        self.assertEqual(m['score'],10038)

    def test_constraint_explanation_uses_actual_scheduling_bounds(self):
        state=small();state['events']=[dict(id='D',kind='delay',train='A',station='S',minutes=10,reason='Signal inspection')]
        row=next(r for r in schedule(state)['rows'] if r['train']=='A')
        self.assertEqual(row['constraints']['earliest_arrival'],490)
        self.assertEqual(row['constraints']['minimum_dwell'],20)
        self.assertEqual(row['constraints']['minimum_gap'],5)
        self.assertIn('Signal inspection',row['reason'])

    def test_search_respects_closures_maintenance_and_gaps(self):
        rng=random.Random(7)
        for _ in range(20):
            state=small()
            state['events']=[dict(id='E',kind='closure',station='S',platform=1,start=475,end=rng.randrange(490,610),reason='Inspection')]
            state['jobs']=[dict(id='J',status='Accepted',station='S',platform=2,start=480,end=510)]
            plan,c=compare_strategies(state)
            self.assertTrue(validate(state,plan)['passed'])
            self.assertLessEqual(c['minimum_disruption']['unscheduled'],c['baseline']['unscheduled'])

    def test_infeasible_comparison_is_explicitly_incomplete(self):
        state=small();state['max_delay']=0
        state['events']=[dict(id='E'+str(p),kind='closure',station='S',platform=p,start=0,end=2880,reason='Closed') for p in (1,2)]
        plan,c=compare_strategies(state)
        self.assertEqual(len(plan['unscheduled']),2)
        self.assertFalse(c['minimum_disruption']['complete'])

    def test_validator_rejects_malformed_preceding_stop_without_crashing(self):
        state=small();state['trains']=state['trains'][:1]
        state['trains'][0]['stops'].append(dict(station='S',arrival=520,departure=525))
        plan=schedule(state);plan['rows'][0]['departure']='bad'
        self.assertFalse(validate(state,plan)['passed'])

    def test_validator_rejects_unknown_unscheduled_identity(self):
        state=small();plan=schedule(state)
        plan['unscheduled'].append(dict(train='GHOST',station='S',stop=0))
        self.assertFalse(validate(state,plan)['passed'])

    def test_am_pm_and_hours_extract_without_state_mutation(self):
        state=small(); before=copy.deepcopy(state)
        result=interpret('Close platform 2 at Rivergate from 9 AM to 10 AM',state)
        self.assertFalse(result['clarification_required'])
        self.assertEqual((result['draft']['start'],result['draft']['end']),(540,600))
        result=interpret('Delay A at S by 2 hours',state)
        self.assertEqual(result['draft']['minutes'],120)
        self.assertNotIn('platform',result['draft'])
        self.assertEqual(state,before)

    def test_ambiguous_missing_negated_and_unsupported_require_clarification(self):
        for text in ('Delay A and B at S by 10 minutes','Delay A at S',
                     'Close platform 1 and platform 2 at S from 09:00 to 10:00',
                     'Do not close platform 1 at S from 09:00 to 10:00',
                     'Delay A at S by 10 minutes and close platform 1',
                     'purple elephants dance','Close platform 1 at S from 10 PM to 9 AM'):
            with self.subTest(text=text):
                self.assertTrue(interpret(text,small())['clarification_required'])

    def test_invalid_platform_and_train_station_are_not_ready(self):
        state=small()
        self.assertTrue(interpret('Close platform 9 at S from 09:00 to 10:00',state)['clarification_required'])
        state['stations'].append(dict(id='OTHER',name='Other',platforms=2,gap=5))
        self.assertTrue(interpret('Delay A at OTHER by 10 minutes',state)['clarification_required'])
