from copy import deepcopy
from datetime import datetime,timezone,timedelta
import unittest
from archive import snapshot,keep_pregame,settle
from test_model import fixture

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,20,22,tzinfo=timezone.utc)
        self.row={'Game ID':'g','Team ID':'A','Player ID':'A2','Tip UTC':'2026-10-20T23:00Z'}
        self.record=snapshot([self.row],'Field goal',self.now)
    def test_only_latest_pregame_is_kept(self):
        saved=keep_pregame(None,self.record,self.now)
        self.assertIsNotNone(saved)
        later=snapshot([self.row],'Field goal',self.now+timedelta(minutes=5))
        self.assertEqual(keep_pregame(saved,later,self.now+timedelta(minutes=5)),later)
        self.assertEqual(keep_pregame(later,saved,self.now+timedelta(minutes=6)),later)
        self.assertEqual(keep_pregame(saved,later,self.now+timedelta(hours=2)),saved)
        self.assertIsNone(keep_pregame(None,later,self.now))
    def test_settlement_preserves_original_forecast(self):
        original=deepcopy(self.record)
        result=settle(self.record,fixture(),self.now+timedelta(hours=4))
        self.assertEqual(self.record,original)
        self.assertEqual(result['rows'],original['rows'])
        self.assertTrue(result['settled_rows'][0]['Game first hit'])
        self.assertEqual(len(result['pregame_sha256']),64)
        wrong=deepcopy(self.record);wrong['rows'][0]['Game ID']='other'
        with self.assertRaises(ValueError):settle(wrong,fixture(),self.now)
        late=deepcopy(self.record);late['created_at']='2026-10-21T01:00Z'
        with self.assertRaises(ValueError):settle(late,fixture(),self.now)

if __name__=='__main__':unittest.main()
