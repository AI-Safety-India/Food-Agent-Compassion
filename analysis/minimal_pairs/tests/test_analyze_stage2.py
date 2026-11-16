"""Stage2 synthetic numerical/guard tests; never reads extraction artifacts."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
spec=importlib.util.spec_from_file_location('stage2',HERE/'analyze_stage2.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class Helper:
    @staticmethod
    def fit_mass_mean(x,y):
        a,b=x[y==1].mean(0),x[y==0].mean(0)
        return ((a-b)/np.linalg.norm(a-b)).astype(np.float32),(a+b)/2
    @staticmethod
    def cosine_sim(a,b):return np.dot(a,b)/np.linalg.norm(a)/np.linalg.norm(b)
    @staticmethod
    def compute_auroc(y,s):
        positive=np.asarray(s)[np.asarray(y)==1];negative=np.asarray(s)[np.asarray(y)==0]
        return ((positive[:,None]>negative).mean()+.5*(positive[:,None]==negative).mean())


def fixture():
    rows=[];arrays=[]
    for subset in('welfare_train','welfare_heldout','neutral_control'):
        for condition,gap in(('none',1.),('welfare',4.),('control',2.)):
            for mirrored in(False,True):
                labels=('line_1','line_2')if subset=='neutral_control'else('better','worse')
                labels=labels[::-1]if mirrored else labels
                rows.append({'pair_id':subset,'set':subset,'mechanism':subset,'condition':condition,'mirrored':mirrored,
                             'A_is':labels[0],'B_is':labels[1],'choice_score':0 if mirrored else 1})
                a=np.zeros((5,2),dtype=np.float32)
                a[0,0]= -gap/2 if mirrored else gap/2
                a[1,0]= gap/2 if mirrored else -gap/2
                a[4,0]=gap
                arrays.append(a)
    return rows,np.stack(arrays)


class Tests(unittest.TestCase):
    def test_paired_contrast_and_ci_not_unpaired(self):
        rows,a=fixture()
        result=m.line_contrasts(rows,a,np.array([1,0]))
        combined=result['combined_welfare']
        self.assertEqual(combined['pairs'],2)
        self.assertEqual(combined['metrics']['welfare-control']['estimate'],2)
        self.assertEqual(combined['metrics']['welfare-control']['interval_95'],[2,2])
        self.assertEqual(combined['metrics']['welfare-none']['estimate'],3)
        self.assertEqual(combined['metrics']['control-none']['estimate'],1)

    def test_missing_condition_or_order_rejected(self):
        rows,a=fixture()
        with self.assertRaisesRegex(ValueError,'three conditions'):
            m.pair_condition_gaps(rows[1:],a[1:,:2,0])

    def test_selected_layer_exact_direction_match(self):
        rows,a=fixture()
        result=m.instruction_curve_point(rows,a,2,Helper(),np.array([1,0],dtype=np.float32),2)
        self.assertEqual(result['cosine'],1)
        self.assertTrue(result['auxiliary_only'])
        with self.assertRaisesRegex(ValueError,'differs'):
            m.instruction_curve_point(rows,a,2,Helper(),np.array([-1,0],dtype=np.float32),2)

    def test_final_targets_and_constant_cases(self):
        rows,a=fixture()
        results=m.final_prediction(rows,a[:,4,0],Helper())
        neutral=next(r for r in results if r['set']=='neutral_control')
        self.assertEqual(neutral['better_choice_auc']['status'],'not_applicable_neutral')
        self.assertEqual(neutral['candidate_A_auc']['status'],'single_class')
        self.assertEqual(neutral['ties'],1)
        welfare=next(r for r in results if r['set']=='welfare_train')
        self.assertEqual(welfare['better_choice_auc']['class_counts'],{'0':1,'1':1})
        self.assertEqual(welfare['better_choice_auc']['value'],.5)
        self.assertEqual(welfare['raw_choice_score_pearson']['status'],'constant_input')

    def test_authorization_guard_precedes_array_read(self):
        with patch.object(np,'load',side_effect=AssertionError('array opened')):
            with self.assertRaisesRegex(ValueError,'authorization'):
                m.run(SimpleNamespace(analysis_authorized=False))


if __name__=='__main__':unittest.main()
