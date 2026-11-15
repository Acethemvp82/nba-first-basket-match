from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import capture
from test_model import fixture
from archive import window_comparison
from model import utc

class CaptureTests(unittest.TestCase):
    def test_capture_then_settle_preserves_pregame_forecast(self):
        now=datetime.now(timezone.utc);tip=now+timedelta(minutes=30)
        event={'id':'g','date':tip.isoformat(),'shortName':'A @ B','status':{'type':{'state':'pre'}},
               'competitions':[{'competitors':[{'team':{'id':t,'abbreviation':t}} for t in ['A','B']]}]}
        historical=fixture();state={'final':False,'projected':False};calls=[]
        extra=deepcopy(historical['plays'][2]);extra['sequenceNumber']='2';extra['participants'][0]['athlete']['id']='A1'
        historical['plays'].append(extra)
        def get(path):
            calls.append(path)
            if path.startswith('scoreboard'):
                return {'events':[] if state['final'] else [event],'season':{'year':2027}}
            if '/schedule?' in path:
                return {'events':[{'id':f'old{i}','date':(now-timedelta(days=i+1)).isoformat(),
                                   'season':{'year':2027},'seasonType':{'type':2},
                                   'competitions':[{'status':{'type':{'completed':True}}}]} for i in range(15)]}
            if path.endswith('/roster'):
                t=path.split('/')[1]
                return {'athletes':[{'id':t+str(i),'displayName':t+str(i)} for i in range(1,6)]}
            if path=='summary?event=g':
                d=deepcopy(historical);comp=d['header']['competitions'][0]
                comp['date']=tip.isoformat()
                comp['status']['type']={'state':'post' if state['final'] else 'pre','completed':state['final']}
                if state['projected']:d['boxscore']['players']=[]
                return d
            if path.startswith('summary?event=old'):return deepcopy(historical)
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as directory:
            data=Path(directory)
            with patch.object(capture,'DATA',data),patch.object(capture.Client,'get',side_effect=get):
                capture.run()
                index=json.loads((data/'index.json').read_text())
                self.assertEqual(len(index['records']),1)
                path=data/index['records'][0]['path']
                original=json.loads(path.read_text())
                self.assertEqual(len(original['rows']),10)
                self.assertEqual(original['basis'],'First points')
                self.assertEqual(original['settings']['games'],15)
                self.assertTrue(all(r['Basis']=='First points' for r in original['rows']))
                self.assertTrue(path.name.endswith('-first-points-last15.json'))
                self.assertEqual(next(r for r in original['rows'] if r['Player ID']=='A1')['Team first hits'],15)
                self.assertEqual(next(r for r in original['rows'] if r['Player ID']=='A2')['Team first hits'],0)
                self.assertTrue(any(r['Shortlisted'] for r in original['rows']))
                self.assertGreater(calls.index('summary?event=g'),calls.index('teams/B/roster'))
                self.assertLessEqual(utc(original['lineup_feed_checked_at']),utc(original['created_at']))
                windows=original['window_forecasts']
                self.assertEqual(set(windows),{'5','10','15'})
                self.assertTrue(all(set(f['players'])==set(windows['15']['players']) for f in windows.values()))
                self.assertTrue(all(abs(sum(f['players'].values())+f['other']-1)<1e-10 for f in windows.values()))
                self.assertNotEqual(windows['5']['players'],windows['15']['players'])
                # A later projected feed should not erase a confirmed snapshot.
                state['projected']=True
                capture.run()
                self.assertEqual(json.loads(path.read_text()),original)
                state['projected']=False
                state['final']=True
                # Move the worker clock beyond tip without changing the saved forecast.
                class Later:
                    @staticmethod
                    def now(tz=None):return (tip+timedelta(hours=3)).astimezone(tz)
                with patch.object(capture,'datetime',Later):capture.run()
                settled=json.loads(path.read_text())
                self.assertEqual(settled['rows'],original['rows'])
                self.assertTrue(settled['settled_rows'])
                self.assertEqual(settled['window_forecasts'],windows)
                comparison=window_comparison([settled,settled],'Source confirmed')
                self.assertEqual([r['Games'] for r in comparison],[1,1,1])
                self.assertEqual(window_comparison([settled],'Projected'),[])
                self.assertTrue(json.loads((data/'index.json').read_text())['records'][0]['settled'])

if __name__=='__main__':unittest.main()

