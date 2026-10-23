import unittest
from copy import deepcopy
from datetime import datetime, timezone
from model import parse_game, forecast, prior_events, implied, opening_context, shot_adjustment, position_profile

def fixture():
    def play(seq,team,pid,made,points,typ='shot'):
        return {'sequenceNumber':str(seq),'team':{'id':team},'participants':[{'athlete':{'id':pid}}],
                'shootingPlay':True,'pointsAttempted':points,'scoreValue':points if made else 0,
                'scoringPlay':made,'period':{'number':1},'clock':{'displayValue':'11:30'}}
    return {'header':{'competitions':[{'id':'g','date':'2026-10-20T23:00Z','status':{'type':{'completed':True}},
              'competitors':[{'team':{'id':t}} for t in ['A','B']]}]},
            'plays':[play(4,'B','B1',True,2),play(1,'A','A1',True,1),play(3,'A','A2',True,2),play(2,'B','B2',False,3)],
            'boxscore':{'players':[{'team':{'id':t},'statistics':[{'athletes':[
                {'athlete':{'id':t+str(i),'displayName':t+str(i)},'starter':True} for i in range(1,6)]}]} for t in ['A','B']]}}

class ModelTests(unittest.TestCase):
    def test_tip_requires_explicit_opening_recipient(self):
        d=fixture();jump={'sequenceNumber':'0','period':{'number':1},'clock':{'displayValue':'12:00'},'type':{'text':'Jumpball'},'team':{'id':'B'},'participants':[{'athlete':{'id':p}} for p in ['A1','B1','A3']],'text':'A1 vs. B1 (A3 gains possession)'}
        d['plays'].append(jump)
        self.assertEqual(parse_game(d)['tip_winner'],'A')
        jump['text']='Unclear possession'
        self.assertIsNone(parse_game(d)['tip_winner'])
        jump['text']='A1 vs. B1 (A3 gains possession)';jump['clock']['displayValue']='6:00'
        self.assertIsNone(parse_game(d)['tip_winner'])
    def test_position_opponent_direction_and_adjustment(self):
        g=parse_game(fixture())
        for t in ['A','B']:
            for i,p in enumerate(g['rosters'][t]):g['rosters'][t][p]['position']=['G','G','F','F','C'][i]
        g['attempts']={'A':'A1','B':'B5'};g['tip_winner']='A'
        own=position_profile([g]*10,'A');allowed=position_profile([g]*10,'B',allowed=True)
        self.assertEqual(own['rates'],allowed['rates'])
        context=opening_context({'A':[g]*10,'B':[g]*10})
        self.assertEqual(shot_adjustment(context['A'],'G'),(1.15,'Favorable'))
        self.assertEqual(shot_adjustment(context['A'],'C'),(.85,'Tougher'))
        self.assertEqual(shot_adjustment(context['A'],'G-F'),(1.0,'Limited data'))
        self.assertAlmostEqual(context['A']['tip_chance']+context['B']['tip_chance'],1)
        self.assertGreater(context['A']['tip_chance'],.5)
        selected={t:sorted(g['starters'][t]) for t in ['A','B']}
        rows,res=forecast({'A':[g]*10,'B':[g]*10},selected,g['rosters'])
        self.assertAlmostEqual(sum(r['Game first %']/100 for r in rows)+sum(res.values()),1)
        small=opening_context({'A':[g]*4,'B':[g]*4})
        self.assertEqual(shot_adjustment(small['A'],'G'),(1.0,'Limited data'))
        self.assertIsNone(small['A']['tip_chance'])
    def test_unknown_positions_are_not_invented(self):
        g=parse_game(fixture());p=position_profile([g],'A')
        self.assertEqual(p['n'],0)
        self.assertTrue(all(v is None for v in p['rates'].values()))
    def test_free_throw_and_order(self):
        d=fixture()
        fg=parse_game(d);points=parse_game(d,'First points')
        self.assertEqual(fg['global_first'],('A','A2'))
        self.assertEqual(points['global_first'],('A','A1'))
        self.assertEqual(fg['attempts']['B'],'B2')
    def test_withhold_missing_or_nonfinal(self):
        d=fixture();d['plays']=[]
        with self.assertRaises(ValueError):parse_game(d)
    def test_fractional_clock(self):
        d=fixture();late=deepcopy(d['plays'][0]);late['sequenceNumber']='500';late['clock']['displayValue']='50.4';d['plays'].append(late)
        self.assertEqual(parse_game(d)['early'][('B','B1')],[1,1])
        d=fixture();d['header']['competitions'][0]['status']['type']['completed']=False
        with self.assertRaises(ValueError):parse_game(d)
    def test_probability_mass_and_sample(self):
        g=parse_game(fixture());hist={t:[g] for t in ['A','B']}
        selected={t:sorted(g['starters'][t]) for t in hist}
        rows,other=forecast(hist,selected,g['rosters'])
        self.assertAlmostEqual(sum(r['Game first %']/100 for r in rows)+sum(other.values()),1)
        for t in hist:self.assertLess(sum(r['Team first %'] for r in rows if r['Team ID']==t),100)
        self.assertTrue(all(r['Sample status']=='Limited' for r in rows))
        self.assertTrue(all(0<r['Game first %']<100 for r in rows))
    def test_starters_validation(self):
        g=parse_game(fixture())
        with self.assertRaises(ValueError):forecast({'A':[g],'B':[g]},{'A':['A1'],'B':['B1']},g['rosters'])
    def test_strict_pregame_cutoff(self):
        def event(id,date,complete=True):return {'id':id,'date':date,'competitions':[{'status':{'type':{'completed':complete}}}]}
        es=[event('past','2026-10-20T23:00Z'),event('same','2026-10-21T23:00Z'),event('future','2026-10-22T23:00Z'),event('unfinished','2026-10-19T23:00Z',False)]
        self.assertEqual([e['id'] for e in prior_events(es,datetime(2026,10,21,23,tzinfo=timezone.utc),20)],['past'])
    def test_odds(self):
        self.assertAlmostEqual(implied(600),1/7)
        self.assertAlmostEqual(implied(-150),.6)
        with self.assertRaises(ValueError):implied(50)

if __name__=='__main__':unittest.main()
