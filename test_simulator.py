import unittest
from model import simulate_first_basket

class SimulatorTests(unittest.TestCase):
    def rows(self):
        return [{'Game ID':'g','Team ID':t,'Player ID':t,'Player':t,'Team':t,'Game first %':p}
                for t,p in [('A',60),('B',30)]]

    def test_probability_mass_and_reproducibility(self):
        result=simulate_first_basket(self.rows(),100000)
        self.assertEqual(result,simulate_first_basket(self.rows(),100000))
        self.assertEqual(sum(r['Simulated first baskets'] for r in result),100000)
        self.assertAlmostEqual(sum(r['Model %'] for r in result),100)
        for r in result:
            self.assertLess(abs(r['Model %']-r['Simulated %']),.6)
        self.assertAlmostEqual(next(r for r in result if r['Player'].startswith('Other'))['Model %'],10)

    def test_certain_outcome(self):
        rows=self.rows(); rows[0]['Game first %']=100;rows[1]['Game first %']=0
        result=simulate_first_basket(rows)
        self.assertEqual(result[0]['Simulated first baskets'],10000)
        self.assertEqual(sum(r['Simulated first baskets'] for r in result[1:]),0)

    def test_reject_invalid_inputs(self):
        for value in [-1,float('nan'),float('inf'),101]:
            rows=self.rows();rows[0]['Game first %']=value
            with self.assertRaises(ValueError):simulate_first_basket(rows)
        rows=self.rows();rows[1]['Game first %']=60
        with self.assertRaises(ValueError):simulate_first_basket(rows)
        rows=self.rows();rows[1]['Game ID']='other'
        with self.assertRaises(ValueError):simulate_first_basket(rows)
        with self.assertRaises(ValueError):simulate_first_basket([])
        with self.assertRaises(ValueError):simulate_first_basket(self.rows(),1000000)
        with self.assertRaises(ValueError):simulate_first_basket(self.rows()*2)
