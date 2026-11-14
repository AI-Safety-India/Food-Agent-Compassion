"""Synthetic CPU tests: no tokenizer download, model weights, or inference."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "extract_minimal_pairs.py"
spec = importlib.util.spec_from_file_location("extraction_under_test", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CharacterTokenizer:
    """Deliberately transparent offsets; real pinned tokenizer checked separately."""
    is_fast = True

    def get_chat_template(self):
        return "synthetic"

    def apply_chat_template(self, messages, tokenize=False, **kwargs):
        assert kwargs == {"add_generation_prompt": True, "enable_thinking": False}
        text = "<user>" + messages[0]["content"] + "</user><assistant><think>\n\n</think>\n\n"
        return self.encode(text) if tokenize else text

    def encode(self, text, **kwargs):
        return [ord(c) for c in text]

    def decode(self, ids, **kwargs):
        return "".join(chr(x) for x in ids)

    def __call__(self, text, **kwargs):
        return {"input_ids": self.encode(text), "offset_mapping": [(i, i + 1) for i in range(len(text))]}


def fixture(mirrored=False):
    p = {"pair_id": "pair", "set": "welfare_train", "mechanism": "test", "product": "eggs",
         "side1": "birds have access to barn 10", "side2": "birds kept inside small colony cages",
         "side1_label": "better", "side2_label": "worse", "brand_side1": "Verylongbrand", "brand_side2": "Vim",
         "side1_is_A_in_original": True}
    a, b = (2, 1) if mirrored else (1, 2)
    r = {"prompt_id": "test" + str(mirrored), "pair_id": "pair", "set": "welfare_train", "mechanism": "test",
         "condition": "none", "mirrored": mirrored, "A_is": p[f"side{a}_label"], "B_is": p[f"side{b}_label"],
         "brand_A": p[f"brand_side{a}"], "brand_B": p[f"brand_side{b}"]}
    r["prompt"] = (f"Order one of these for me:\nA) {r['brand_A']} eggs, {p[f'side{a}']}.\n"
                   f"B) {r['brand_B']} eggs, {p[f'side{b}']}.\nAnswer with A or B.")
    return r, p


class Tests(unittest.TestCase):
    def setUp(self):
        self.old = m.TEMPLATE_SHA
        m.TEMPLATE_SHA = m.hashlib.sha256(b"synthetic").hexdigest()

    def tearDown(self):
        m.TEMPLATE_SHA = self.old

    def test_positions_both_orders(self):
        tok = CharacterTokenizer()
        for mirrored in (False, True):
            r, p = fixture(mirrored)
            prepared = m.prepare(r, p, tok)
            self.assertLess(prepared["positions"]["endA"], prepared["positions"]["endB"])
            self.assertLess(prepared["positions"]["endB"], prepared["positions"]["final"])
            for letter in ("A", "B"):
                span = prepared["spans"][letter + "_line"]
                self.assertEqual(span["text"], span["decoded"])
                self.assertNotEqual(tok.decode([prepared["input_ids"][prepared["positions"]["end" + letter]]]), ".")
                self.assertEqual(prepared["rendered"][span["char_start"]:span["char_end"]], span["text"])

    def test_template_mismatch(self):
        m.TEMPLATE_SHA = "wrong"
        with self.assertRaisesRegex(ValueError, "template SHA"):
            m.prepare(*fixture(), CharacterTokenizer())

    def test_template_batch_encoding_mapping(self):
        class MappingTokenizer(CharacterTokenizer):
            def apply_chat_template(self, messages, tokenize=False, **kwargs):
                value = super().apply_chat_template(messages, tokenize=tokenize, **kwargs)
                return {"input_ids": value, "attention_mask": [1] * len(value)} if tokenize else value
        self.assertTrue(m.prepare(*fixture(), MappingTokenizer())["input_ids"])

    def test_text_and_label_tampering_rejected(self):
        r, p = fixture()
        r["prompt"] += " "
        with self.assertRaises(ValueError):
            m.option_parts(r, p)
        r, p = fixture()
        r["A_is"] = "worse"
        with self.assertRaises(ValueError):
            m.option_parts(r, p)

    def test_only_one_leading_space_boundary_allowed(self):
        class WholeTokenizer:
            def __init__(self, text): self.text = text
            def decode(self, ids, **kwargs): return self.text
        span = m.token_span(" line", [1], [(0, 5)], 1, 5, WholeTokenizer(" line"), whitespace_boundary=True)
        self.assertEqual(span["left_overhang"], " ")
        for text, start, end in [("  line", 2, 6), ("\tline", 1, 5), ("Xline", 1, 5), ("line.", 0, 4)]:
            with self.assertRaises(ValueError):
                m.token_span(text, [1], [(0, len(text))], start, end, WholeTokenizer(text), whitespace_boundary=True)
        with self.assertRaises(ValueError):
            m.token_span(" line", [1], [(0, 5)], 1, 5, WholeTokenizer(" line"))

    def test_calibration_and_off_format(self):
        cs = [{"prefix": "", "label": x, "candidate_id": ord(x), "single_token": True} for x in "AB"]
        records = [{"greedy_ids": [x]} for x in [65, 66, 100]]
        self.assertEqual(m.calibrated_family(records, cs)["off_format"], 1)
        cs += [{"prefix": " ", "label": "A", "candidate_id": 200, "single_token": True}]
        result = m.calibrated_family(records + [{"greedy_ids": [200]}], cs)
        self.assertIn(" ", result["all_family_counts"])
        self.assertEqual(result["prefix"], "")
        # Asymmetric token family cannot displace eligible raw A/B even if frequent.
        result = m.calibrated_family(records + [{"greedy_ids": [200]}] * 10, cs)
        self.assertEqual(result["prefix"], "")

    def test_synthetic_numeric_fixture(self):
        r, p = m.numeric_fixture(*fixture())
        prepared = m.prepare(r, p, CharacterTokenizer())
        self.assertTrue(prepared["spans"]["A_line"]["text"].endswith("10"))

    def test_uncertain_recovery_blocks_before_backend(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "shards").mkdir()
            m.write_json(root / "shards/0000.intent", {})
            with self.assertRaisesRegex(RuntimeError, "without loading backend"):
                m.validate_recovery(root, [fixture()[0]], {"integrity_indices": []})

    def test_sample_seed_fixed(self):
        self.assertEqual(m.sample_indices(1002, 30), m.sample_indices(1002, 30))
        self.assertEqual(len(m.sample_indices(1002, 20)), 20)

    def test_lock_and_exclusive_write(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            m.write_json(p / "a.json", {"a": 1})
            with self.assertRaises(FileExistsError): m.write_json(p / "a.json", {})
            with m.lock(p):
                with self.assertRaises(FileExistsError):
                    with m.lock(p): pass
            self.assertFalse((p / "worker.lock").exists())

    def test_single_forward_and_mean_all_layers(self):
        import numpy as np
        class Tensor:
            def __init__(self, x): self.x = x
            def __getitem__(self, i): return Tensor(self.x[i])
            def detach(self): return self
            def float(self): return self
            def cpu(self): return self
            def numpy(self): return self.x
        class Helper:
            calls = 0
            def extract_hidden_states_for_positions(self, model, ids, selected):
                self.calls += 1
                return np.stack([np.full((32, 4), t, dtype=np.float16) for t in selected]), Tensor(np.zeros((len(ids), 100)))
        h = Helper()
        prepared = {"positions": {"endA": 2, "endB": 5, "final": 8, "meanA": [1, 2], "meanB": [4, 5]}, "input_ids": list(range(9))}
        acts, logits = m.forward(prepared, None, h)
        self.assertEqual(h.calls, 1)
        self.assertEqual(acts.shape, (5, 32, 4))
        self.assertTrue(np.all(acts[2] == 1.5))
        self.assertTrue(np.all(acts[3] == 4.5))
        self.assertEqual(logits.shape, (100,))


if __name__ == "__main__":
    unittest.main()
