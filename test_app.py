"""Streamlit smoke test with controlled source data; never queries live services."""
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from copy import deepcopy
from test_model import fixture

class AppTest(unittest.TestCase):
    def test_board_uses_first_points(self):
        from streamlit.testing.v1 import AppTest as StreamlitTest
        now=datetime.now(ZoneInfo('America/New_York'))
        tip=(now+timedelta(days=1)).isoformat()
        teams=[{'team':{'id':t,'displayName':t,'abbreviation':t}} for t in ['A','B']]
        future={'id':'future','date':tip,'shortName':'A @ B','status':{'type':{'state':'pre','detail':'Scheduled','completed':False}},'competitions':[{'competitors':teams}]}
        future_two={**future,'id':'future2','shortName':'B @ A'}
        past={'id':'g','date':(now-timedelta(days=1)).isoformat(),'season':{'year':2027},'seasonType':{'type':2},'competitions':[{'status':{'type':{'completed':True}}}]}
        data=fixture();data['header']['competitions'][0]['date']=past['date']
        extra=deepcopy(data['plays'][2]);extra['sequenceNumber']='2';extra['participants'][0]['athlete']['id']='A1'
        data['plays'].append(extra)
        lineup_state={'ready':False}
        def refresh(at):
            next(b for b in at.button if b.label=='Refresh data').click().run()
            return at
        def fake(path):
            if path.startswith('scoreboard'):return {'events':[future,future_two],'season':{'year':2027}}
            if '/schedule?' in path:return {'events':[{**past,'id':f'g{i}','date':(now-timedelta(days=i+1)).isoformat()} for i in range(5)]}
            if path in ['summary?event=future','summary?event=future2']:
                current=deepcopy(data);comp=current['header']['competitions'][0]
                comp.update({'id':path.split('=')[1],'date':tip,'status':{'type':{'state':'pre','completed':False}}})
                if not lineup_state['ready']:current['boxscore']['players']=[]
                return current
            if path.startswith('summary'):return deepcopy(data)
            if path.endswith('/roster'):
                tid=path.split('/')[1]
                return {'athletes':[{'id':tid+str(i),'displayName':tid+str(i),'position':{'abbreviation':'C'}} for i in range(1,7)]}
            raise AssertionError(path)
        with patch('model.fetch',side_effect=fake):
            at=StreamlitTest.from_file(str(Path(__file__).with_name('app.py')),default_timeout=30).run()
            self.assertFalse(at.exception)
            # The simulator also works before the prediction board is loaded.
            next(x for x in at.multiselect if x.label=='Simulator matchups').set_value(['future','future2']).run()
            self.assertFalse(at.exception)
            self.assertEqual(sum('Simulated first baskets' in d.value.columns for d in at.dataframe),2)
            self.assertFalse(any(m.label=='Players ranked' for m in at.metric))
            next(x for x in at.multiselect if x.label=='Simulator matchups').set_value(['future']).run()
            next(b for b in at.button if b.label=='Load / update prediction board').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(next(m for m in at.metric if m.label=='Players ranked').value,'10')
            self.assertTrue(at.session_state['automatic_pregame_records'])
            next(x for x in at.multiselect if x.label=='Simulator matchups').set_value(['future']).run()
            self.assertFalse(at.exception)
            sim=next(d.value for d in at.dataframe if 'Simulated first baskets' in d.value.columns)
            self.assertEqual(len(sim),11)
            self.assertEqual(int(sim['Simulated first baskets'].sum()),10000)
            self.assertTrue((sim[sim['Player']!='Other / unlisted players']['Research tier']=='Awaiting starters').all())
            next(x for x in at.selectbox if x.label=='Simulated games per matchup').set_value(50000).run()
            self.assertFalse(at.exception)
            sim=next(d.value for d in at.dataframe if 'Simulated first baskets' in d.value.columns)
            self.assertEqual(int(sim['Simulated first baskets'].sum()),50000)
            board=next(d.value for d in at.dataframe if 'Research tier' in d.value.columns)
            self.assertTrue((board['Research tier']=='Awaiting starters').all())
            self.assertTrue(board['Why ranked'].str.contains('Limited history').all())
            details=next(d.value for d in at.dataframe if 'Opponent first FG allowed count' in d.value.columns)
            self.assertTrue((details['Opponent first FG games']==0).all())
            self.assertFalse(any('Pick' in d.value.columns for d in at.dataframe))
            self.assertFalse(any('verified' in box.label.lower() for box in at.checkbox))
            self.assertFalse(any(x.label=='Select five starters' for x in at.multiselect))
            lineup_state['ready']=True
            refresh(at)
            self.assertFalse(at.exception)
            shortlist=next(d.value for d in at.dataframe if 'Pick' in d.value.columns)
            self.assertEqual(len(shortlist),1)
            self.assertEqual(shortlist.iloc[0]['Player'],'A1')
            self.assertEqual(shortlist.iloc[0]['Research tier'],'Limited data')
            price=next(x for x in at.number_input if x.label.startswith('American odds —'))
            self.assertIsNone(price.value)
            price.set_value(650).run()
            self.assertFalse(at.exception)
            self.assertEqual(next(d.value for d in at.dataframe if 'Pick' in d.value.columns).iloc[0]['Your odds'],'+650')
            # Missing source confirmation must remove eligibility automatically.
            lineup_state['ready']=False
            refresh(at)
            self.assertFalse(at.exception)
            self.assertFalse(any('Pick' in d.value.columns for d in at.dataframe))
            self.assertFalse(any(r.label=='Settlement basis' for r in at.radio))
            for record in at.session_state['automatic_pregame_records'].values():
                self.assertEqual(record['basis'],'First points')
                self.assertTrue(all(r['Basis']=='First points' for r in record['rows']))
            next(b for b in at.button if b.label=='Load / update prediction board').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(next(m for m in at.metric if m.label=='Players ranked').value,'10')
            self.assertTrue(any('First points' in c.value and 'simulated games' in c.value for c in at.caption))
            # Add the second matchup in the simulator without changing the board.
            next(x for x in at.multiselect if x.label=='Simulator matchups').set_value(['future','future2']).run()
            self.assertFalse(at.exception)
            self.assertEqual(next(m for m in at.metric if m.label=='Players ranked').value,'10')
            self.assertEqual(set(at.session_state['automatic_pregame_records']),{'First points:future'})
            picker=next(x for x in at.multiselect if x.label=='Simulator matchups')
            self.assertEqual(picker.value,['future','future2'])
            trials=next(x for x in at.selectbox if x.label=='Simulated games per matchup').value
            sims=[d.value for d in at.dataframe if 'Simulated first baskets' in d.value.columns]
            self.assertEqual([int(s['Simulated first baskets'].sum()) for s in sims],[trials,trials])
            picker.set_value(['future2']).run()
            self.assertFalse(at.exception)
            self.assertEqual(sum('Simulated first baskets' in d.value.columns for d in at.dataframe),1)
            next(x for x in at.multiselect if x.label=='Simulator matchups').set_value([]).run()
            self.assertFalse(at.exception)
            self.assertFalse(any('Simulated first baskets' in d.value.columns for d in at.dataframe))

if __name__=='__main__':unittest.main()



