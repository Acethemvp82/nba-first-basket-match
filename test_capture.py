from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import capture
from test_model import fixture

class CaptureTests(unittest.TestCase):
    def test_capture_then_settle_preserves_pregame_forecast(self):
        now=datetime.now(timezone.utc);tip=now+timedelta(minutes=30)
        event={'id':'g','date':tip.isoformat(),'shortName':'A @ B','status':{'type':{'state':'pre'}},
               'competitions':[{'competitors':[{'team':{'id':t,'abbreviation':t}} for t in ['A','B']]}]}
        historical=fixture();state={'final':False}
        def get(path):
            if path.startswith('scoreboard'):
                return {'events':[] if state['final'] else [event],'season':{'year':2027}}
            if '/schedule?' in path:
                return {'events':[{'id':f'old{i}','date':(now-timedelta(days=i+1)).isoformat(),
                                   'season':{'year':2027},'seasonType':{'type':2},
                                   'competitions':[{'status':{'type':{'completed':True}}}]} for i in range(5)]}
            if path.endswith('/roster'):
                t=path.split('/')[1]
                return {'athletes':[{'id':t+str(i),'displayName':t+str(i)} for i in range(1,6)]}
            if path=='summary?event=g':
                d=deepcopy(historical);comp=d['header']['competitions'][0]
                comp['date']=tip.isoformat()
                comp['status']['type']={'state':'post' if state['final'] else 'pre','completed':state['final']}
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
                self.assertTrue(any(r['Shortlisted'] for r in original['rows']))
                state['final']=True
                # Move the worker clock beyond tip without changing the saved forecast.
                class Later:
                    @staticmethod
                    def now(tz=None):return (tip+timedelta(hours=3)).astimezone(tz)
                with patch.object(capture,'datetime',Later):capture.run()
                settled=json.loads(path.read_text())
                self.assertEqual(settled['rows'],original['rows'])
                self.assertTrue(settled['settled_rows'])
                self.assertTrue(json.loads((data/'index.json').read_text())['records'][0]['settled'])

if __name__=='__main__':unittest.main()
