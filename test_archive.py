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


class TrackingSummaryTests(unittest.TestCase):
    def record(self):
        rows=[{'Game ID':'g','Team ID':'A','Player ID':f'A{i}','Player':f'Player {i}',
               'Game first %':30-i,'Tip UTC':'2026-10-20T23:00Z','Overall Rank':i+2,
               'Team Rank':i,'Matchup':'A @ B','Lineup':'Projected','Shortlisted':i==1}
              for i in range(1,5)]
        r=snapshot(rows,'First points',datetime(2026,10,20,22,tzinfo=timezone.utc))
        r['settings']={'games':15}
        r['settled_rows']=[{**row,'Game first hit':row['Player ID']=='A2'} for row in rows]
        return r

    def test_summary_uses_saved_ranks_and_deduplicates(self):
        from archive import tracking_summary
        r=self.record();older=deepcopy(r);older['created_at']='2026-10-20T21:00Z'
        wrong=deepcopy(r);wrong['basis']='Field goal'
        rows=tracking_summary([r,older,wrong])
        self.assertEqual(len(rows),1)
        result=rows[0]
        self.assertEqual(result['First scorer'],'Player 2')
        self.assertEqual(result['Pregame game rank'],2)
        self.assertEqual(result['Pregame overall rank'],4)
        self.assertFalse(result['Top pick hit']);self.assertTrue(result['Top 3 hit'])
        self.assertFalse(result['Shortlist hit'])
        self.assertEqual(result['Lineup'],'Projected')

    def test_pending_unlisted_and_late_records(self):
        from archive import tracking_summary
        r=self.record();r.pop('settled_rows')
        row=tracking_summary([r])[0]
        self.assertEqual(row['Status'],'Pending');self.assertIsNone(row['Top pick hit'])
        r['settled_rows']=[{**x,'Game first hit':False} for x in r['rows']]
        r['first_scorer']={'Player':'Bench scorer'}
        row=tracking_summary([r])[0]
        self.assertEqual(row['First scorer'],'Bench scorer');self.assertIsNone(row['Pregame game rank'])
        r['created_at']='2026-10-21T00:00Z'
        self.assertEqual(tracking_summary([r]),[])
