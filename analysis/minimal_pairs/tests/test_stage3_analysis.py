import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import analyze_stage3_steering as a

class AnalysisTests(unittest.TestCase):
    def test_target_orientation_and_pair_weight(self):
        rows=[]
        for pair in ['p1','p2']:
            for target in ['A','B']:
                for mirror in [False,True]:
                    rows.append(dict(direction=0,set='welfare_heldout',pair_id=pair,alpha=4,target=target,
                        target_is='better' if (target=='A')!=mirror else 'worse',
                        candidate_logits=[2,0] if target=='A' else [0,2],baseline_logits=[0,0]))
        s=a.summary(rows,0,['welfare_heldout'])
        self.assertEqual(s['n_pairs'],2)
        self.assertAlmostEqual(s['effects']['4']['mean'],a.probability([2,0])-.5)
        self.assertEqual(s['effects']['0']['ci95'],[0,0])
        b=a.summary(rows,0,['welfare_heldout'],'better')
        self.assertEqual(b['effects'],s['effects'])

    def test_missing_mirror_rejected(self):
        with self.assertRaises(AssertionError):
            a.summary([dict(direction=0,set='x',pair_id='p',alpha=4,target='A',target_is='better',
                            candidate_logits=[2,0],baseline_logits=[0,0])],0,['x'])

    def test_pass_requires_same_dose(self):
        def curve(negative,positive):
            return dict(monotonic=True,effects={str(k):dict(mean=v,ci95=[v-.001,v+.001]) for k,v in [(-4,negative),(4,positive)]})
        primary=curve(-.2,.2);neutral=curve(-.05,.05);random=[curve(-.01,.01) for _ in range(10)]
        self.assertEqual(a.criteria(primary,neutral,random)['verdict'],'PASS')
        primary['monotonic']=False
        self.assertEqual(a.criteria(primary,neutral,random)['verdict'],'FAIL')
        primary['monotonic']=True
        self.assertEqual(a.criteria(primary,curve(-.11,.11),random)['verdict'],'FAIL')
        self.assertEqual(a.criteria(primary,neutral,[curve(-.1,.1) for _ in range(10)])['verdict'],'FAIL')

if __name__=='__main__':unittest.main()
