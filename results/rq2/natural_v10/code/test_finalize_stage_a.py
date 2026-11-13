"""Synthetic-only review freeze validation; no repository data read."""
import copy
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finalize_stage_a import combine, freeze, evaluate, verify_committed, assistant_text_sha
from input_adapter import InputBlocked, RUBRIC_VERSION, review_status, file_sha


class ReviewFreezeTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 64
        self.groups = [dict(group_id='G0000', assistant_text_sha256='b' * 64,
            rubric_sha256='c' * 64, rubric_version=RUBRIC_VERSION,
            members=[dict(review_id='prefix_' + self.sha[:24], prefix_sha256=self.sha)])]
        self.one = [dict(group_id='G0000', assistant_text_sha256='b' * 64,
                         decision='clean', reviewer='reviewer_c', rationale='Synthetic prose')]
        self.two = [dict(self.one[0], reviewer='reviewer_b')]
        self.groups[0]['assistant_messages'] = [{'message': {'role': 'assistant', 'content': 'Synthetic prose'}}]
        self.text_sha = assistant_text_sha(self.groups[0]['assistant_messages'])
        for row in (self.groups[0], self.one[0], self.two[0]):
            row['assistant_text_sha256'] = self.text_sha

    def combine(self, first=None, second=None, adj=None):
        return combine(self.groups, self.one if first is None else first,
                       self.two if second is None else second, adj or [], 'c' * 64, 1, 1)

    def test_agreement_preserves_identity_and_adapter_contract(self):
        rows = self.combine()
        self.assertEqual(rows[0]['reviewer_1'], 'reviewer_c')
        self.assertEqual(rows[0]['adjudicator'], 'independent_agreement')
        self.assertEqual(review_status({rows[0]['review_id']: rows[0]}, rows[0]['review_id'], self.sha, 'c' * 64), 'clean')

    def test_missing_review_rejected(self):
        with self.assertRaises(InputBlocked): self.combine(first=[])

    def test_wrong_hash_rejected(self):
        bad = [dict(self.one[0], assistant_text_sha256='d' * 64)]
        with self.assertRaises(InputBlocked): self.combine(first=bad)

    def test_missing_adjudication_rejected(self):
        bad = [dict(self.two[0], decision='welfare')]
        with self.assertRaises(InputBlocked): self.combine(second=bad)

    def test_adjudicated_ambiguity_remains_unknown(self):
        second = [dict(self.two[0], decision='welfare')]
        adj = [dict(group_id='G0000', assistant_text_sha256=self.text_sha,
                    decision='ambiguous', adjudicator='root_blinded_prefix_adjudication', rationale='Unclear')]
        self.assertEqual(self.combine(second=second, adj=adj)[0]['prefix_review'], 'unknown')

    def test_duplicate_review_rejected(self):
        with self.assertRaises(InputBlocked): self.combine(first=self.one * 2)

    def test_changed_message_with_unchanged_declared_hash_rejected(self):
        self.groups[0]['assistant_messages'][0]['message']['content'] = 'Different text'
        with self.assertRaisesRegex(InputBlocked, 'content hash mismatch'): self.combine()

    def test_wrong_member_hash_rejected(self):
        self.groups[0]['members'][0]['prefix_sha256'] = 'd' * 64
        with self.assertRaises(InputBlocked): self.combine()


class SyntheticEndToEndTests(unittest.TestCase):
    """All dataset and outcome bytes are generated in a disposable directory.

    Commit lookup is mocked from an immutable byte snapshot; never invokes Git.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'stage'
        packets = self.stage / 'review_packets'
        packets.mkdir(parents=True)
        self.rubric = self.root / 'rubric.txt'
        self.rubric.write_text('synthetic rubric', encoding='utf-8')
        self.rq1 = self.root / 'rq1.csv'
        self.tuning = self.root / 'tuning.json'
        self.frozen = self.root / 'frozen'
        self.groups, streams = [], {'a': [], 'b': [], 'c': []}
        member_index = 0
        for i in range(731):
            members = []
            for _ in range(2 if i < 667 else 1):
                sha = hashlib.sha256(str(member_index).encode()).hexdigest()
                members.append(dict(review_id='prefix_' + sha[:24], prefix_sha256=sha))
                member_index += 1
            messages = [{'message': {'role': 'assistant', 'content': 'Synthetic assistant ' + str(i)}}]
            text_sha = assistant_text_sha(messages)
            g = dict(group_id=f'G{i:04d}', assistant_text_sha256=text_sha,
                     assistant_messages=messages, rubric_version=RUBRIC_VERSION, rubric_sha256=file_sha(self.rubric), members=members)
            self.groups.append(g)
            for stream in ('a' if i < 500 else 'c', 'b'):
                streams[stream].append(dict(group_id=g['group_id'], assistant_text_sha256=text_sha,
                    reviewer='reviewer_' + stream, decision='clean', rationale='Synthetic review'))
        (packets / 'batch_000.json').write_text(json.dumps(self.groups), encoding='utf-8')
        (packets / 'groups.json').write_text(json.dumps(self.groups), encoding='utf-8')
        for stream, rows in streams.items():
            (self.stage / f'reviewer_{stream}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
        (self.stage / 'adjudications.jsonl').write_text('', encoding='utf-8')
        self.records = []
        member = self.groups[0]['members'][0]
        for i in range(50):
            for score in (0, 2):
                states = [dict(option_id=role, harmful=harmful, causal_order=[0, n],
                    available_layers=list(range(1,33)), finite_layers=list(range(1,33)),
                    provenance_verified=True, prefix_review='welfare',
                    provenance=dict(member, prefix_review_basis='semantic_review_or_unknown'))
                    for n, (role, harmful) in enumerate((('h', True), ('s', False)))]
                self.records.append(dict(run_id=f's{i}_{score}', scenario_id=f's{i}',
                    prompt_condition='neutral', score_a=score, variant='base', epoch=1, states=states))
        (self.stage / 'normalized_records.json').write_text(json.dumps(self.records), encoding='utf-8')
        self.tuning.write_text(json.dumps([dict(scenario_id=f's{i}') for i in range(10)]), encoding='utf-8')
        with self.rq1.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=['run_id','scenario_id','prompt_condition','score_a','variant','epoch','outcome'])
            w.writeheader()
            for r in self.records:
                w.writerow({**{k:v for k,v in r.items() if k!='states'}, 'outcome':'synthetic'})

    def do_freeze(self):
        freeze(self.stage, self.frozen, self.rq1, self.tuning, self.rubric)

    def commit_snapshot(self):
        manifest = json.loads((self.frozen / 'source_hashes.json').read_text(encoding='utf-8'))
        paths = [self.frozen/n for n in ('source_hashes.json','prefix_reviews.csv','review_summary.json')]
        paths += list(map(Path, manifest['code_paths']))
        snapshot = {p.resolve():p.read_bytes() for p in paths}
        return patch('finalize_stage_a.committed_bytes', side_effect=lambda repo, commit, path: snapshot[path.resolve()])

    def test_freeze_never_parses_outcome_inputs(self):
        for path in (self.rq1, self.tuning, self.stage/'normalized_records.json'):
            path.write_text('not valid structured data', encoding='utf-8')
        self.do_freeze()
        summary = json.loads((self.frozen/'review_summary.json').read_text())
        self.assertEqual(summary['prefixes'], 1398)
        self.assertFalse(summary['outcome_data_parsed'])
        with self.assertRaises(InputBlocked): self.do_freeze()

    def test_full_evaluate_uses_reviews_and_unchanged_gate(self):
        self.do_freeze()
        out = self.root/'result'
        with self.commit_snapshot():
            evaluate(self.root, self.frozen, out, 'a'*40, 'outcome')
        summary = json.loads((out/'summary.json').read_text())
        self.assertEqual(summary['paired_positive_counts'], {'development':10,'evaluation':40})
        self.assertTrue(summary['feasible'])
        self.assertEqual(len(json.loads((out/'pair_manifest.json').read_text())), 50)

    def test_groups_and_batches_must_match(self):
        self.groups[0]['assistant_messages'][0]['message']['content'] = 'Different reviewed text'
        (self.stage/'review_packets/groups.json').write_text(json.dumps(self.groups), encoding='utf-8')
        with self.assertRaisesRegex(InputBlocked, 'differ from batch'): self.do_freeze()
        self.assertFalse(self.frozen.exists())

    def test_groups_source_is_hashed(self):
        self.do_freeze()
        manifest = json.loads((self.frozen/'source_hashes.json').read_text(encoding='utf-8'))
        path = self.stage/'review_packets/groups.json'
        self.assertIn({'path':str(path.resolve()), 'sha256':file_sha(path)}, manifest['sources'])

    def test_source_mutation_blocks_before_parse(self):
        self.do_freeze()
        with self.commit_snapshot(), patch('finalize_stage_a.read_csv') as parse_csv:
            self.rq1.write_text('changed', encoding='utf-8')
            with self.assertRaises(InputBlocked):
                evaluate(self.root, self.frozen, self.root/'result', 'a'*40, 'outcome')
            parse_csv.assert_not_called()

    def test_uncommitted_csv_blocks(self):
        self.do_freeze()
        with self.commit_snapshot():
            with (self.frozen/'prefix_reviews.csv').open('a',encoding='utf-8') as f: f.write('\n')
            with self.assertRaises(InputBlocked): verify_committed(self.root,self.frozen,'a'*40)

    def test_invalid_commit_blocks(self):
        with self.assertRaises(InputBlocked): verify_committed(self.root,self.frozen,'not-a-commit')


if __name__ == '__main__':
    unittest.main()
