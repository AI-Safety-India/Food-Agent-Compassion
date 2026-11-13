"""Synthetic orchestration checks; no project records or Git are read."""
import copy
import tempfile
import unittest
from pathlib import Path
from run_stage_a import selected_review_ids, save_outputs, InputBlocked


def record():
    return {'score_a': 2, 'states': [
        {'harmful': h, 'option_id': str(i), 'causal_order': [i, 0],
         'provenance_verified': True, 'available_layers': list(range(1, 33)),
         'finite_layers': list(range(1, 33)), 'prefix_review': 'unknown',
         'provenance': {'review_id': 'p' + str(i)}}
        for i, h in enumerate((True, False))]}


class RunnerTests(unittest.TestCase):
    def test_selected_common_sample_only(self):
        r = record()
        self.assertEqual(selected_review_ids([r]), {'p0', 'p1'})
        r['states'][0]['provenance_verified'] = False
        self.assertFalse(selected_review_ids([r]))
        later = copy.deepcopy(r['states'][0])
        later.update(provenance_verified=True, causal_order=[10, 0])
        r['states'].append(later)
        self.assertFalse(selected_review_ids([r]))

    def test_excludes_score1_and_completed_review(self):
        r = record()
        r['score_a'] = 1
        self.assertFalse(selected_review_ids([r]))
        r['score_a'] = 0
        r['states'][0]['prefix_review'] = 'clean'
        self.assertEqual(selected_review_ids([r]), {'p1'})
        r['states'][1]['prefix_review'] = 'welfare'
        self.assertFalse(selected_review_ids([r]))

    def test_no_gate_and_no_overwrite(self):
        result = {'records': [record()], 'issues': [], 'source_ledger': [],
                  'blinded_prefix_review': [{'review_id': p, 'assistant_messages': []}
                                            for p in ('p0', 'p1')]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'new'
            summary = save_outputs(out, result, {'prereg_commit': 'a' * 40})
            self.assertEqual(summary['status'], 'pending_prefix_review')
            self.assertFalse(summary['final_feasibility_gate_evaluated'])
            with self.assertRaises(FileExistsError):
                save_outputs(out, result, {'prereg_commit': 'a' * 40})

    def test_missing_chronology_stops(self):
        r = record()
        del r['states'][0]['causal_order']
        with self.assertRaises(InputBlocked):
            selected_review_ids([r])


if __name__ == '__main__':
    unittest.main()
