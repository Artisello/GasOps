import unittest, json
from pathlib import Path
from gasops import gas_hours, run, settlement
class Tests(unittest.TestCase):
    def setUp(self): self.s=json.loads(Path(__file__).with_name('example.json').read_text())
    def test_dst(self):
        self.assertEqual(gas_hours('2026-03-28'),23)
        self.assertEqual(gas_hours('2026-10-24'),25)
        self.assertEqual(gas_hours('2026-11-17'),24)
    def test_missing(self):
        self.s['expected_demand_mwh']=None
        r=run(self.s)
        self.assertEqual(r['status'],'BLOCKED_REVIEW')
        self.assertNotIn('balance_screen',[a['agent'] for a in r['agents']])
    def test_notice(self): self.assertEqual(run(self.s)['status'],'BLOCKED_REVIEW')
    def test_cashflow(self):
        self.assertEqual(settlement(self.s)['signed_user_cashflow_eur'],'-50400.00')
        self.s['user_imbalance_mwh']=100
        self.assertEqual(settlement(self.s)['signed_user_cashflow_eur'],'3800.00')
    def test_zero(self):
        self.s['user_imbalance_mwh']=0
        self.assertEqual(settlement(self.s)['direction'],'none')
    def test_read_only(self):
        self.s['data_kind']='live'
        with self.assertRaises(ValueError): run(self.s)
if __name__=='__main__': unittest.main()
