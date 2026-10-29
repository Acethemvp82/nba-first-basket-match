"""Streamlit smoke test with controlled source data; never queries live services."""
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from copy import deepcopy
from test_model import fixture

class AppTest(unittest.TestCase):
    def test_board_and_market_switch(self):
        from streamlit.testing.v1 import AppTest as StreamlitTest
        now=datetime.now(ZoneInfo('America/New_York'))
        tip=(now+timedelta(days=1)).isoformat()
        teams=[{'team':{'id':t,'displayName':t,'abbreviation':t}} for t in ['A','B']]
        future={'id':'future','date':tip,'shortName':'A @ B','status':{'type':{'state':'pre','detail':'Scheduled','completed':False}},'competitions':[{'competitors':teams}]}
        past={'id':'g','date':(now-timedelta(days=1)).isoformat(),'season':{'year':2027},'seasonType':{'type':2},'competitions':[{'status':{'type':{'completed':True}}}]}
        data=fixture();data['header']['competitions'][0]['date']=past['date']
        def fake(path):
            if path.startswith('scoreboard'):return {'events':[future],'season':{'year':2027}}
            if '/schedule?' in path:return {'events':[{**past,'id':f'g{i}','date':(now-timedelta(days=i+1)).isoformat()} for i in range(5)]}
            if path.startswith('summary'):return deepcopy(data)
            if path.endswith('/roster'):
                tid=path.split('/')[1]
                return {'athletes':[{'id':tid+str(i),'displayName':tid+str(i),'position':{'abbreviation':'C'}} for i in range(1,7)]}
            raise AssertionError(path)
        with patch('model.fetch',side_effect=fake):
            at=StreamlitTest.from_file(str(Path(__file__).with_name('app.py')),default_timeout=30).run()
            self.assertFalse(at.exception)
            next(b for b in at.button if b.label=='Load / update prediction board').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(next(m for m in at.metric if m.label=='Players ranked').value,'10')
            board=next(d.value for d in at.dataframe if 'Research tier' in d.value.columns)
            self.assertTrue((board['Research tier']=='Limited data').all())
            self.assertTrue(board['Why ranked'].str.contains('Limited history').all())
            details=next(d.value for d in at.dataframe if 'Opponent first FG allowed count' in d.value.columns)
            self.assertTrue((details['Opponent first FG games']==0).all())
            self.assertFalse(any('Pick' in d.value.columns for d in at.dataframe))
            for box in at.checkbox:
                if box.label=='I verified these five starters and availability':box.check()
            at.run()
            self.assertFalse(at.exception)
            shortlist=next(d.value for d in at.dataframe if 'Pick' in d.value.columns)
            self.assertEqual(len(shortlist),1)
            self.assertEqual(shortlist.iloc[0]['Player'],'A2')
            price=next(x for x in at.number_input if x.label.startswith('American odds —'))
            self.assertIsNone(price.value)
            price.set_value(650).run()
            self.assertFalse(at.exception)
            self.assertEqual(next(d.value for d in at.dataframe if 'Pick' in d.value.columns).iloc[0]['Your odds'],'+650')
            # A changed lineup must require a fresh user confirmation.
            lineup=next(x for x in at.multiselect if x.label=='Select five starters')
            vals=list(lineup.value);vals[-1]='A6'
            lineup.set_value(vals).run()
            self.assertFalse(any('Pick' in d.value.columns for d in at.dataframe))
            next(r for r in at.radio if r.label=='Settlement basis').set_value('First points').run()
            next(b for b in at.button if b.label=='Load / update prediction board').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(next(m for m in at.metric if m.label=='Players ranked').value,'10')

if __name__=='__main__':unittest.main()
