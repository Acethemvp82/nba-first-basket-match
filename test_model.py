import unittest
from copy import deepcopy
from datetime import datetime, timezone
from model import parse_game, forecast, prior_events, implied

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
