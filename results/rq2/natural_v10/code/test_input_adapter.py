"""Synthetic schema tests only; no study data or learned scores accessed."""
import io
import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
import numpy as np
import input_adapter as a


class AdapterTests(unittest.TestCase):
    def test_gate_precedes_io(self):
        with self.assertRaises(a.InputBlocked):
            a.adapt({})

    def test_unknown_not_clean(self):
        self.assertEqual(a.review_status({}, 'x', 'hash'), 'unknown')
        self.assertFalse(a.structurally_empty_assistant([{'role':'assistant'}], 'logged_request'))
        self.assertFalse(a.structurally_empty_assistant([{'role':'assistant','content':'','reasoning_content':'harm'}], 'logged_request'))
        self.assertFalse(a.structurally_empty_assistant([{'role':'assistant','content':'','tool_calls':[{'arguments':'harm'}]}], 'logged_request'))
        self.assertTrue(a.structurally_empty_assistant([{'role':'assistant','content':None}], 'logged_request'))
        self.assertFalse(a.structurally_empty_assistant([], 'reconstructed_request'))

    def test_dual_review_and_hash(self):
        row={'prefix_sha256':'hash','prefix_review':'clean','rubric_version':a.RUBRIC_VERSION,
             'reviewer_1':'one','reviewer_2':'two','decision_1':'clean','decision_2':'clean','adjudicator':'one','rationale':'read all'}
        self.assertEqual(a.review_status({'x':row},'x','hash'),'clean')
        with self.assertRaises(a.InputBlocked):a.review_status({'x':row},'x','hash','frozen_rubric_hash')
        row['rubric_sha256']='frozen_rubric_hash'
        self.assertEqual(a.review_status({'x':row},'x','hash','frozen_rubric_hash'),'clean')
        with self.assertRaises(a.InputBlocked): a.review_status({'x':row},'x','changed')
        row['reviewer_2']='one'
        with self.assertRaises(a.InputBlocked): a.review_status({'x':row},'x','hash')
        row['prefix_review']='ambiguous'
        self.assertEqual(a.review_status({'x':row},'x','hash'),'unknown')

    def test_preserves_all_reasoning(self):
        m=a.assistant_message({'role':'assistant','reasoning_content':'first', 'content':[
            {'type':'reasoning','internal':'reasoning_content','reasoning':'second'},
            {'type':'reasoning','internal':'reasoning_content','reasoning':'third'},
            {'type':'text','text':'visible'}]})
        self.assertEqual(m['reasoning_content'],'first\nsecond\nthird')
        self.assertIn('visible',m['content'])

    def test_causal_boundary_no_future(self):
        tool={'role':'tool','tool_call_id':'t','content':'Option Details:\n  ID: toy\ntext'}
        before={'role':'assistant','content':'past'}
        calls=[({'messages':[before,tool]},'logged_request'),
               ({'messages':[before,tool,{'role':'assistant','content':'FUTURE'}]},'logged_request')]
        ci,mi,source,prefix,sha=a.causal_prefix(calls,1,0,'toy')
        self.assertEqual((ci,mi),(0,1))
        self.assertNotIn('FUTURE',json.dumps(prefix))
        with self.assertRaises(a.InputBlocked):a.causal_prefix(calls,1,0,'wrong')

    def test_reference_reconstruction(self):
        message={'role':'assistant','content':'known','reasoning_content':'reason'}
        s={'events':[{'event':'model','input_refs':[[0,1]]}], 'events_data':{'messages':[message]}}
        calls=a.requests(s)
        self.assertEqual(calls[0][0]['messages'][0]['reasoning_content'],'reason')
        self.assertEqual(calls[0][1],'reconstructed_request')

    def test_original_npz_no_token_array(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); payload=io.BytesIO()
            np.savez_compressed(payload,hidden_states=np.zeros((2,32,4096),dtype=np.float16))
            with zipfile.ZipFile(td/'cache.zip','w') as z:z.writestr('toy.npz',payload.getvalue())
            with zipfile.ZipFile(td/'repair.zip','w') as z:z.writestr('report.json',json.dumps({'completed_jobs':[]}))
            states=a.ArchiveStates([td/'cache.zip'],td/'repair.zip')
            row={'run_id':'toy','activation_source':'original_cache','activation_file':'toy.npz','activation_token_index':'7','sub_idx':'0'}
            got=states.load(row,0,{},2)
            self.assertEqual(got['finite_layers'],list(range(1,33)))
            self.assertEqual(got['activation_ref']['coordinate_basis'],'audited_position_metadata_not_embedded_in_npz')
            with self.assertRaises(a.InputBlocked):states.load(row,0,{},3)
            row['activation_file']='wrong.npz'
            with self.assertRaises(a.InputBlocked):states.load(row,0,{},2)
            states.close()

    def test_synthetic_end_to_end_adapter_and_blinding(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            def write(name, obj):
                p=td/name;p.write_text(json.dumps(obj),encoding='utf-8');return str(p)
            def csvfile(name, row):
                p=td/name
                with p.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
                return str(p)
            rid='neutral__toy_base__ep1'
            pos={'run_id':rid,'target_call_idx':0,'pos_a':[{'sub_idx':0,'option_id':'toy','option_label':'harmful','tok_idx':7}],'pos_b':[],'pos_c':None}
            original=write('positions.jsonl',pos)
            helper=write('helper.json',{'synthetic':True})
            audit=write('audit.json',{'input_hashes':{'positions':a.file_sha(original),'replay_helper':a.file_sha(helper)},'runs':[{'run_id':rid,'target_call':0,'calls':[{'call':0,'source':'logged_request','matches_final_prefix':True}]}]})
            repair=td/'repair.zip'
            with zipfile.ZipFile(repair,'w') as z:z.writestr('report.json',json.dumps({'completed_jobs':[],'environment':{'audit_sha256':a.file_sha(audit)}}))
            cache=td/'cache.zip';payload=io.BytesIO()
            np.savez_compressed(payload,hidden_states=np.zeros((1,32,4096),dtype=np.float16))
            with zipfile.ZipFile(cache,'w') as z:z.writestr(rid+'.npz',payload.getvalue())
            log=td/'sample.eval'
            sample={'id':'toy_base','epoch':1,'events':[{'event':'model','call':{'request':{'messages':[{'role':'assistant','content':''},{'role':'tool','tool_call_id':'t','content':'Option Details:\n  ID: toy\nlisting'}]}},'output':{'content':'FUTURE'}}]}
            with zipfile.ZipFile(log,'w') as z:z.writestr('samples/toy.json',json.dumps(sample))
            prereg=write('prereg.json',{'synthetic':True});rubric=write('rubric.json',{'synthetic':True})
            config={'prereg_commit':'a'*40,'preregistration':prereg,'prereg_sha256':a.file_sha(prereg),'original_positions':original,'repaired_positions':original,'replay_helper':helper,'cpu_audit':audit,'repair_audit':write('repair_audit.json',{'metadata_only_positions':[]}),'repair_zip':str(repair),'cache_zips':[str(cache)],'eval_logs':{'neutral':str(log)},'prefix_rubric':rubric,
                    'rq1_csv':csvfile('rq1.csv',{'run_id':rid,'scenario_id':'toy','prompt_condition':'neutral','score_a':0,'variant':'base','epoch':1}),
                    'repaired_scores':csvfile('scores.csv',{'run_id':rid,'pos_type':'pos_a','sub_idx':0,'option_id':'toy','tok_idx':7,'activation_source':'original_cache','activation_file':rid+'.npz','activation_token_index':7})}
            result=a.adapt(config);state=result['records'][0]['states'][0]
            self.assertTrue(state['provenance_verified']);self.assertEqual(state['prefix_review'],'clean')
            sheet=result['blinded_prefix_review'][0]
            self.assertNotIn('score_a',sheet);self.assertNotIn('FUTURE',json.dumps(sheet));self.assertNotIn('listing',json.dumps(sheet))
            review={'review_id':sheet['review_id'],'prefix_sha256':sheet['prefix_sha256'],'rubric_version':a.RUBRIC_VERSION,'rubric_sha256':a.file_sha(rubric),'prefix_review':'ambiguous'}
            config['prefix_reviews']=csvfile('reviews.csv',review)
            again=a.adapt(config)
            self.assertEqual(again['records'][0]['states'][0]['prefix_review'],'unknown')


if __name__=='__main__':unittest.main()
