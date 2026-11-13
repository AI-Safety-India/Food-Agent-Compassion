"""Synthetic only: no vLLM, tokenizer, model imports or network."""
import gzip
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
import capacity_runner as c


def job(jid='j1'):
    ids = [1, 2, 3]
    return dict(job_id=jid, input_ids=ids, input_ids_json_sha256=c.jsha(ids),
                base_token_prefix_preserved=True, historical_reasoning_omission_flag=False,
                status='not_ready_pending_reference_and_generation_config_freeze')


def output(ids, finish='stop', text='Yes. Specific concern.'):
    return NS(prompt_token_ids=ids, request_id='backend-1',
              outputs=[NS(text=text, token_ids=[4, 5], finish_reason=finish, stop_reason=9)])


class Tests(unittest.TestCase):
    def test_environment_preserved_and_changes_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'environment.json'
            c.preserve_environment(p,{'gpu':'original','quantization':None})
            original=p.read_bytes()
            c.preserve_environment(p,{'gpu':'original','quantization':None})
            self.assertEqual(p.read_bytes(),original)
            with self.assertRaises(ValueError):
                c.preserve_environment(p,{'gpu':'changed','quantization':None})
            self.assertEqual(p.read_bytes(),original)

    def test_startup_failure_creates_no_intent(self):
        with tempfile.TemporaryDirectory() as td:
            def prepare(): raise ImportError('synthetic startup')
            with self.assertRaises(ImportError):
                c.run_jobs([job()],td,{},lambda ids:self.fail('no dispatch'),prepare=prepare)
            self.assertFalse((Path(td)/'ledger.jsonl').exists())
            self.assertEqual(json.loads((Path(td)/'summary.json').read_text())['completed'],0)
            c.run_jobs([job()],td,{},output)

    def test_recovery_before_startup_and_completed_skips_startup(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[]
            c.run_jobs([job()],td,{},output,prepare=lambda:calls.append('startup'))
            c.run_jobs([job()],td,{},output,prepare=lambda:self.fail('already done'))
            self.assertEqual(calls,['startup'])
            self.assertEqual(json.loads((Path(td)/'summary.json').read_text())['completed'],1)

    def test_bundle_hash_and_identity(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); j = job(); raw = gzip.compress(json.dumps([j]).encode())
            (p/'prepared.json.gz').write_bytes(raw)
            m = dict(schema='capacity_runner_v1', model_revision=c.REVISION,
                     runner_sha256=c.file_sha(c.__file__),
                     engine=c.ENGINE, sampling=c.SAMPLING, prepared_file='prepared.json.gz',
                     prepared_sha256=c.sha(raw), job_count=1, jobs={'j1': c.jsha(j)})
            mp = p/'manifest.json'; mp.write_text(json.dumps(m))
            digest = c.sha(mp.read_bytes())
            self.assertEqual(c.read_bundle(mp, digest)[1], [j])
            with self.assertRaises(ValueError): c.read_bundle(mp, 'bad')
            bad=dict(m,runner_sha256='bad'); mp.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'Runner bytes'):
                c.read_bundle(mp,c.sha(mp.read_bytes()))
            mp.write_text(json.dumps(m))
            (p/'prepared.json.gz').write_bytes(raw+b'x')
            with self.assertRaises(ValueError): c.read_bundle(mp, digest)

    def test_sequential_intent_before_dispatch_and_no_repeat(self):
        with tempfile.TemporaryDirectory() as td:
            calls = []
            def generate(ids):
                events = [json.loads(x) for x in (Path(td)/'ledger.jsonl').read_text().splitlines()]
                self.assertEqual(events[-1]['event'], 'intent')
                calls.append(ids); return output(ids)
            jobs = [job('a'), job('b')]
            self.assertEqual(len(c.run_jobs(jobs, td, {'frozen': 1}, generate)), 2)
            c.run_jobs(jobs, td, {'frozen': 1}, generate)
            self.assertEqual(len(calls), 2)
            with self.assertRaises(ValueError): c.run_jobs(jobs, td, {'frozen': 2}, generate)

    def test_uncertain_intent_blocks_all_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            c.append_event(Path(td)/'ledger.jsonl', dict(event='intent', job_id='b',
                           input_hash=c.jsha([1,2,3]), request_id='r'))
            calls=[]
            with self.assertRaises(RuntimeError):
                c.run_jobs([job('a'),job('b')], td, {}, lambda x: calls.append(x),
                           prepare=lambda:self.fail('uncertain ledger must block startup'))
            self.assertFalse(calls)

    def test_atomic_response_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            intent=dict(event='intent', job_id='j1', input_hash=c.jsha([1,2,3]), request_id='r')
            c.append_event(Path(td)/'ledger.jsonl', intent)
            c.atomic_json(Path(td)/'j1.json', dict(job_id='j1', input_hash=intent['input_hash'],
                          request_id='r', completion='complete'))
            result=c.run_jobs([job()],td,{},lambda x: self.fail('Must not regenerate'))
            self.assertEqual(result[0]['completion'],'complete')
            self.assertIn('completion',(Path(td)/'ledger.jsonl').read_text())

    def test_failure_persisted_never_retried(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[]
            def fail(ids): calls.append(ids); raise OSError('synthetic')
            with self.assertRaises(RuntimeError): c.run_jobs([job()],td,{},fail)
            self.assertEqual(c.run_jobs([job()],td,{},fail)[0]['completion'],'generation_failure')
            self.assertEqual(len(calls),1)

    def test_prompt_mismatch_stops_and_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                c.run_jobs([job()],td,{},lambda ids:output([999]))
            r=json.loads((Path(td)/'j1.json').read_text())
            self.assertFalse(r['input_ids_equal']); self.assertEqual(r['prompt_token_ids'],[999])

    def test_truncation_and_malformed_not_semantic_failure(self):
        self.assertEqual(c.serialize_output(output([1,2,3],'length'),job())['completion'],'token_limit_truncated')
        self.assertEqual(c.serialize_output(output([1,2,3],text=''),job())['completion'],'no_final_answer')
        self.assertEqual(c.serialize_output(output([1,2,3],text='<think>oops'),job())['completion'],'malformed_or_ambiguous')

    def test_tamper_and_lock(self):
        with tempfile.TemporaryDirectory() as td:
            c.run_jobs([job()],td,{},output)
            (Path(td)/'j1.json').write_text('{}')
            with self.assertRaises((KeyError,ValueError)): c.run_jobs([job()],td,{},output)
            (Path(td)/'RUNNING.lock').write_text('')
            with self.assertRaises(FileExistsError): c.run_jobs([job()],td,{},output)


if __name__=='__main__': unittest.main()
