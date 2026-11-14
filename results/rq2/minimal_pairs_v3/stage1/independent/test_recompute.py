"""Synthetic-only checks for independent recomputation."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('independent',Path(__file__).with_name('recompute.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Tests(unittest.TestCase):
 def rows(self):return [{'pair_id':'p','mirrored':False,'A_is':'better','B_is':'worse','mechanism':'m'},{'pair_id':'p','mirrored':True,'A_is':'worse','B_is':'better','mechanism':'m'}]
 def test_mirrors_and_ties(self):
  r=m.accuracy([[1,1],[0,2]],self.rows());self.assertEqual((r['correct'],r['ties'],r['total']),(1,1,2));self.assertEqual(m.pair_average([3,-3],self.rows()),{'p':0})
 def test_rank_auc(self):
  self.assertEqual(m.auc([0,1,0,1],[0,2,1,3]),1);self.assertEqual(m.auc([0,1],[1,1]),.5);self.assertEqual(m.auc([0,1],[2,1]),0)
 def test_cluster_intervals(self):self.assertEqual(m.ci([0,0,1,1],['a','a','b','b']),[0,1])
 def test_binary_bow(self):
  b={'binary':True,'lowercase':True,'token_pattern':'[a-z]+','vocabulary':{'a':0,'b':1},'coefficient':[2.,-1.],'intercept':.5}
  r=[{'spans':{'A_line':{'text':'A A unknown'},'B_line':{'text':'B'}}}]
  np.testing.assert_equal(m.bow_scores(b,r),[[2.5,-.5]])
if __name__=='__main__':unittest.main()
