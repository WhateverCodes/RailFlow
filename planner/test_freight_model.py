import csv
import io
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from freight_model import HEADERS,IST,read_history,train,status


def history():
    output=io.StringIO();writer=csv.writer(output);writer.writerow(HEADERS)
    for i in range(42*24):
        t=datetime(2025,1,1,tzinfo=IST)+timedelta(hours=i)
        writer.writerow(['TEST-SECTION',t.isoformat(),2 if t.hour<6 else 0,'true','QA generated observations; not railway data'])
    return output.getvalue()


class FreightTests(unittest.TestCase):
    def test_chronological_training_and_no_false_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);m=train(history(),'QA generated fixture',['TEST-SECTION'],root)
            self.assertLess(m['training_end'],m['holdout_start'])
            self.assertEqual(m['rows'],42*24)
            self.assertEqual(m['baseline_mae'],0)
            self.assertFalse(m['eligible_for_activation'])
            self.assertIsNone(status(root)['active'])
            self.assertTrue((root/m['id']/'model.joblib').exists())

    def test_rejects_missing_duplicate_future_and_unconfirmed_hours(self):
        text=history();lines=text.splitlines()
        bad=[text.replace(',true,',',false,',1),'\n'.join(lines[:-1]),text+'\n'+lines[1],text.replace('2025-01-01','2099-01-01',1)]
        for value in bad:
            with self.assertRaises(ValueError):read_history(value,['TEST-SECTION'])

    def test_rejects_unknown_section_and_timetable_schema(self):
        with self.assertRaises(ValueError):read_history(history(),['OTHER'])
        with self.assertRaises(ValueError):read_history('train_no,departure\n12345,06:00',['TEST-SECTION'])


if __name__=='__main__':unittest.main()
