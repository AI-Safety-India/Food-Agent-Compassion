"""Synthetic training-isolation/CV tests; no actual activation input is opened."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

spec = importlib.util.spec_from_file_location("train", Path(__file__).resolve().parents[1]/"train_stage1.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Helper:
    @staticmethod
    def fit_mass_mean(x, y):
        a,b=x[y==1].mean(0),x[y==0].mean(0)
        return (a-b)/max(np.linalg.norm(a-b),1e-12),(a+b)/2
    @staticmethod
    def score_mass_mean(x,w,midpoint): return (x-midpoint)@w


class Tests(unittest.TestCase):
    def test_pairwise_tie_not_half_credit(self):
        score=m.pairwise_count([1,0,2,2,0,1],[1,0,1,0,0,1])
        self.assertEqual(score,{'correct':2,'total':3,'ties':1})

    def test_selection_ties_lower_layer_then_c(self):
        rows=[{'accuracy':.7,'layer':2,'C':.001},{'accuracy':.7,'layer':1,'C':10},
              {'accuracy':.7,'layer':1,'C':.0001}]
        for row in rows:row.update(correct=7,total=10)
        self.assertEqual(m.select(rows,secondary=True)['C'],.0001)
        self.assertEqual(m.select(rows)['layer'],1)

    def test_lomo_both_orders_kept_together_and_single_c(self):
        rows=[{'mechanism':mech,'A_is':'better' if order==0 else 'worse','B_is':'worse' if order==0 else 'better'}
              for mech in ('one','two') for order in (0,1)]
        a=np.zeros((4,2,32,2),dtype=np.float32)
        for i,row in enumerate(rows):
            for side,letter in enumerate(('A','B')):
                a[i,side,:,0]=1 if row[letter+'_is']=='better' else -1
                a[i,side,:,1]=10 if i<2 else 20
        calls=[]
        def adapter(x,y,c):
            # A fold sees only one mechanism marker, never validation marker.
            self.assertEqual(len(set(x[:,1])),1)
            self.assertEqual(len(x),4)
            calls.append(c)
            return {'direction':np.array([1,0]),'intercept':0}
        result=m.cross_validate(a,rows,Helper(),adapter)
        self.assertEqual(len(calls),32*2*len(m.C_GRID))
        self.assertEqual(len(result['primary']),32)
        self.assertEqual(len(result['secondary']),192)
        self.assertEqual(result['selected_primary']['layer'],1)
        self.assertEqual(result['selected_secondary']['C'],.0001)

    def test_nontrain_rejected_before_np_load(self):
        with patch.object(np,'load',side_effect=AssertionError('activation opened')):
            with self.assertRaisesRegex(ValueError,'non-training'):
                m.load_training_arrays('.', [{'set':'welfare_heldout','condition':'none','shard_file':'mixed.npz'}])

    def test_metadata_hash_failure_before_array_open(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'prompts.jsonl';p.write_text('{}\n')
            with patch.object(np,'load',side_effect=AssertionError('activation opened')):
                with self.assertRaisesRegex(ValueError,'prompts digest'):
                    m.validate_training_index(td,p)

    def test_freeze_drift_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'primary.npz').write_bytes(b'direction')
            frozen={'code_commit':'a'*40,'files':{'primary.npz':m.sha(root/'primary.npz')},'sources':{}}
            m.write_new(root/'FROZEN.json',frozen)
            digest=m.sha(root/'FROZEN.json')
            with patch.object(m,'verify_code_commit') as verify:
                self.assertEqual(m.verify_frozen(root,digest,'a'*40,'b'*40)['code_commit'],'a'*40)
                verify.assert_called_once()
            (root/'primary.npz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'drift'):m.verify_frozen(root,digest,'a'*40,'b'*40)

    def test_training_length_residualizer_removes_nuisance(self):
        lengths=np.array([5,5,8,8],dtype=float)
        y=np.array([1,0,1,0])
        x=np.column_stack([3+2*lengths, y*2-1])
        fit=m.length_adjusted_mass_mean(x,y,lengths,Helper())
        np.testing.assert_allclose(fit['residual_slope'],[2,0],atol=1e-12)
        residual=x-fit['residual_intercept']-lengths[:,None]*fit['residual_slope']
        np.testing.assert_allclose(residual[:,0],0,atol=1e-12)
        self.assertGreater(fit['direction'][1],.99)

    def test_single_c_scaling_and_effective_score(self):
        x=np.array([[1.,10.],[2.,20.],[5.,40.],[6.,50.]])
        y=np.array([0,0,1,1])
        fit=m.single_c_logistic(x,y,.1)
        np.testing.assert_allclose(fit['mean'],x.mean(0))
        np.testing.assert_allclose(fit['scale'],x.std(0))
        raw=x@fit['direction']+fit['intercept']
        standardized=((x-fit['mean'])/fit['scale'])@fit['coefficient_standardized']+fit['intercept_standardized']
        np.testing.assert_allclose(raw,standardized,atol=1e-12)

    def test_bow_vocabulary_uses_original_training_lines_only(self):
        rows=[]
        for i in range(70):
            rows.append({'pair_id':str(i),'mirrored':False,'A_is':'better','B_is':'worse',
                         'spans':{'A_line':{'text':'alpha shared'},'B_line':{'text':'beta shared'}}})
            rows.append({'pair_id':str(i),'mirrored':True,'A_is':'worse','B_is':'better',
                         'spans':{'A_line':{'text':'excluded sentinel'},'B_line':{'text':'excluded sentinel'}}})
        fit=m.fit_bow_training(rows)
        self.assertEqual(set(fit['vocabulary']),{'alpha','beta','shared'})
        self.assertEqual(fit['training_line_instances'],140)


if __name__=='__main__':unittest.main()
