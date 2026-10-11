import copy
import csv
import io
import unittest
from railflow.domain import base_state, mutate, public_state
from railflow.engine import schedule
from railflow.strategies import compare_strategies
from railflow.validator import validate
from railflow.reports import csv_bytes, dataset, pdf_bytes, departure_status, clock

AUTH=dict(role='authority',station=None,name='Authority',username='AUTHORITY')


class ReportTests(unittest.TestCase):
    def test_csv_unicode_escaping_empty_and_formula_injection(self):
        values=['पुणे, महाराष्ट्र','"Quoted"\nsecond line',None,'=HYPERLINK("bad")','  +CMD','\t@SUM(1)','plain']
        raw=csv_bytes(['text','minutes'],[dict(text=v,minutes=-5) for v in values])
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['text'],values[0]);self.assertEqual(rows[1]['text'],values[1])
        self.assertEqual(rows[2]['text'],'')
        for i in (3,4,5):self.assertEqual(rows[i]['text'],"'"+values[i])
        self.assertTrue(all(r['minutes']=='-5' for r in rows))

    def test_csv_empty_report_has_headers(self):
        self.assertEqual(csv_bytes(['train'],[]).decode('utf-8-sig'),'train\r\n')

    def test_timetable_station_filter_and_master_scope(self):
        s=base_state();u={**AUTH,'role':'master','station':'PUNE'}
        headers,records=dataset(s,u,'timetable')
        self.assertTrue(records);self.assertTrue(all(r['station']=='PUNE' for r in records))
        self.assertEqual(len(records),sum(r['station']=='PUNE' for r in s['plan']['rows']))
        with self.assertRaises(PermissionError):dataset(s,u,'timetable',station='LNL')

    def test_customer_restricted_and_redacted(self):
        s=base_state();u={**AUTH,'role':'customer'}
        s['plan']['rows'][0]['reason']='Confidential platform issue'
        _,rows=dataset(public_state(s,u),u,'timetable')
        self.assertNotIn('Confidential',str(rows))
        for kind in ('history','disruptions','backlog'):
            with self.assertRaises(PermissionError):dataset(s,u,kind)

    def test_backlog_uses_only_real_records(self):
        s=base_state();_,rows=dataset(s,AUTH,'backlog')
        self.assertTrue(all(r['status']=='Turnaround risk' for r in rows))
        self.assertTrue(all('priority' not in r and 'created_at' not in r for r in rows))

    def test_disruption_report_does_not_invent_incident_date(self):
        s=base_state();mutate(s,AUTH,dict(action='event',event=dict(kind='delay',train='RF101',station='PUNE',minutes=20,reason='पुणे - मराठी सूचना')))
        _,rows=dataset(s,AUTH,'disruptions')
        self.assertEqual(rows[0]['reason'],'पुणे - मराठी सूचना')
        self.assertEqual(rows[0]['created_at'],'Unavailable')
        self.assertIn('RF101',rows[0]['latest_recorded_changes'])

    def test_overnight_early_departure_not_early_arrival(self):
        self.assertEqual(clock(1450,'2026-10-11'),'2026-10-12 00:10')
        self.assertEqual(departure_status(dict(departure=1450,scheduled_departure=1460)),'Early departure')
        self.assertEqual(departure_status(dict(departure=1460,scheduled_departure=1460,arrival=1400,scheduled_arrival=1410)),'On-time departure')

    def test_pdf_unicode_and_empty_records_are_valid(self):
        s=base_state()
        for rows in ([],[dict(reason='पुणे महाराष्ट्र प्लेटफॉर्म - हिंदी सूचना')]):
            pdf=pdf_bytes('RailFlow - Disruption report',['reason'],rows,s,AUTH)
            self.assertTrue(pdf.startswith(b'%PDF-'));self.assertTrue(pdf.rstrip().endswith(b'%%EOF'))
            self.assertIn(b'/FontFile2',pdf)

    def test_pdf_large_report_paginates(self):
        s=base_state();_,rows=dataset(s,AUTH,'timetable')
        pdf=pdf_bytes('RailFlow - Timetable',['train','station_name','arrival','departure','reason'],rows,s,AUTH)
        self.assertGreater(pdf.count(b'/Type /Page\n'),1)


class RecoveryWorkflowTests(unittest.TestCase):
    def state(self):
        return dict(stations=[dict(id='S',name='Station',platforms=1,gap=5)],trains=[dict(id=str(i),name=str(i),stops=[dict(station='S',arrival=480,departure=490,required_platform=1)]) for i in range(3)],events=[],jobs=[],max_delay=60)

    def test_conflict_requires_multiple_delays(self):
        s=self.state();plan,comparison=compare_strategies(s)
        self.assertTrue(validate(s,plan)['passed']);self.assertFalse(plan['unscheduled'])
        self.assertEqual(sorted(r['delay'] for r in plan['rows']),[0,15,30])

    def test_closure_infeasibility_has_bounds_and_does_not_mutate(self):
        s=self.state();s['events']=[dict(id='C',kind='closure',station='S',platform=1,start=0,end=2880,reason='Closed')]
        before=copy.deepcopy(s);plan,c=compare_strategies(s)
        self.assertEqual(s,before);self.assertTrue(c['recovery_attempted'])
        self.assertEqual(len(plan['unscheduled']),3);self.assertFalse(validate(s,plan)['complete'])
        self.assertEqual(plan['unscheduled'][0]['constraints']['blocks'][0]['id'],'C')
        self.assertIn('No restriction was relaxed',plan['unscheduled'][0]['review'])

    def test_recovery_order_can_complete_when_original_greedy_cannot(self):
        s=self.state();s['stations'][0]['platforms']=2;s['max_delay']=0
        s['trains']=s['trains'][:2];s['trains'][0]['stops'][0]['required_platform']=None
        self.assertTrue(schedule(s)['unscheduled'])
        plan,c=compare_strategies(s)
        self.assertFalse(plan['unscheduled']);self.assertTrue(validate(s,plan)['passed'])
        self.assertEqual(next(r['platform'] for r in plan['rows'] if r['train']=='0'),2)
