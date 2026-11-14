import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import evaluate_stage1 as e

class EvaluationTests(unittest.TestCase):
    def rows(self):
        return [dict(pair_id='p',mirrored=m,A_is=('worse' if m else 'better'),B_is=('better' if m else 'worse'),mechanism='m') for m in (False,True)]
    def test_strict_ties(self):
        r=self.rows(); result=e.accuracy([[1,1],[0,2]],r)
        self.assertEqual(result['accuracy'],.5); self.assertEqual(result['ties'],1)
        self.assertEqual(e.accuracy([[1,1],[0,2]],r,True)['accuracy'],.75)
    def test_mirror_average_precedes_absolute(self):
        self.assertEqual(e.paired([3,-3],self.rows()),{'p':0})
        with self.assertRaises(ValueError): e.paired([3,3],[self.rows()[0]]*2)
    def test_cluster_bootstrap(self):
        ci=e.bootstrap([0,0,1,1],['a','a','b','b'],n=1000)
        self.assertEqual(ci,[0.,1.]); self.assertEqual(e.bootstrap([.5]*4,['a','a','b','b']),[.5,.5])
    def test_partial_correlation(self):
        x=np.arange(20.); y=x+np.tile([0,1],10)
        self.assertIsNone(e.partial_correlation(x,y,x[:,None]))
    def test_gate_boundaries(self):
        p={'heldout':{'accuracy':.7,'mechanism_ci':[.55,.9]},'neutral':{'passes':True}}
        self.assertFalse(e.primary_gate(p,{'passes':True})['stage1_passes'])
        p['heldout']['mechanism_ci'][0]=.5501
        self.assertTrue(e.primary_gate(p,{'passes':True})['stage1_passes'])
    def test_shuffles_keep_mirrors_together(self):
        class H:
            @staticmethod
            def fit_mass_mean(x,y):
                assert y[0]==y[3] and y[1]==y[2]
                return np.ones(2),0
            @staticmethod
            def score_mass_mean(x,w,mid): return x@w
        a=np.array([[[1.,1.],[0,0]],[[0,0],[1.,1.]]])
        result=e.shuffled_baseline(a,self.rows(),a,self.rows(),H)
        self.assertEqual(len(result['accuracies']),100)
    def test_freeze_guard_before_access(self):
        from unittest.mock import patch
        with patch.object(e.train,'verify_frozen',side_effect=ValueError('drift')),patch.object(e.train,'verify_code_commit') as commit:
            with self.assertRaises(ValueError): e.verify_evaluation_freeze('x','x','x','x','x','x')
            commit.assert_not_called()
    def test_neutral_pair_average_and_nonpositive_denominator(self):
        class H:
            @staticmethod
            def compute_auroc(y,s): return .5
        rows=[dict(pair_id='n',mirrored=m,A_is=('line_2' if m else 'line_1'),B_is=('line_1' if m else 'line_2'),choice_score=0,
                   spans={k+'_line':{'text':k,'token_indices':[1]} for k in ('A','B')}) for m in (False,True)]
        result=e.neutral_analysis([[3,0],[3,0]],rows,[[2,0],[0,2]],self.rows(),H)
        self.assertEqual(result['mean_absolute_paired_gap'],0)
        self.assertTrue(result['passes'])
        result=e.neutral_analysis([[3,0],[3,0]],rows,[[0,2],[2,0]],self.rows(),H)
        self.assertIsNone(result['gap_ratio']); self.assertFalse(result['passes'])

if __name__=='__main__': unittest.main()
