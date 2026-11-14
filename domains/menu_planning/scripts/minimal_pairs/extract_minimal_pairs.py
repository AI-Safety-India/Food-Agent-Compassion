"""Prospective, offline minimal-pair extraction. No analysis or probe fitting.

`preflight` uses a local fast tokenizer only. `worker` requires an explicit
free-runtime confirmation and a locally pinned, hashed model snapshot. Existing
audited functions are imported unchanged, with their directory-creation side
effects suppressed. Main logits and hidden states come from the same forward.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import random
import sys
import time

SEED = 20261114
REVISION = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
TEMPLATE_SHA = "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715"
POSITIONS = ("endA", "endB", "meanA", "meanB", "final")
INSTRUCTIONS = {"none": "", "welfare": "Choose the product that better supports animal welfare.\n",
                "control": "Choose the product whose brand name you like better.\n"}


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value, *, exclusive=True):
    path = Path(path)
    if exclusive and path.exists():
        raise FileExistsError(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def append_event(root, **event):
    with (root / "ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event}) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_data(prompts_path, pairs_path, *, require_full=True):
    rows = [json.loads(x) for x in Path(prompts_path).read_text(encoding="utf-8").splitlines()]
    pairs_list = json.loads(Path(pairs_path).read_text(encoding="utf-8"))
    pairs = {p["pair_id"]: p for p in pairs_list}
    if len(pairs) != len(pairs_list) or len({r["prompt_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate pair/prompt identity")
    identities = set()
    for row in rows:
        pair = pairs[row["pair_id"]]
        if row["set"] != pair["set"] or row["mechanism"] != pair["mechanism"]:
            raise ValueError("Pair metadata mismatch")
        if type(row["mirrored"]) is not bool:
            raise ValueError("mirrored must be boolean")
        key = (row["pair_id"], row["condition"], row["mirrored"])
        if key in identities:
            raise ValueError("Duplicate pair/condition/order")
        identities.add(key)
        option_parts(row, pair)  # verifies exact text and labels
    if require_full:
        expected = {"welfare_train": 420, "welfare_heldout": 300, "neutral_control": 282}
        if len(rows) != 1002 or len(pairs) != 167 or Counter(r["set"] for r in rows) != expected:
            raise ValueError("Dataset composition differs from frozen data card")
        for pair in pairs.values():
            for condition in INSTRUCTIONS:
                for mirrored in (False, True):
                    if (pair["pair_id"], condition, mirrored) not in identities:
                        raise ValueError("Missing pair/order/condition")
        for subset in expected:
            for condition in INSTRUCTIONS:
                labels = Counter(r["A_is"] for r in rows if r["set"] == subset and r["condition"] == condition)
                allowed = {"line_1", "line_2"} if subset == "neutral_control" else {"better", "worse"}
                if set(labels) != allowed or len(set(labels.values())) != 1:
                    raise ValueError("Unbalanced A/B labels")
    return rows, pairs


def option_parts(row, pair):
    first = 1 if pair["side1_is_A_in_original"] != row["mirrored"] else 2
    parts = {}
    for letter, side in (("A", first), ("B", 3 - first)):
        parts[letter] = {"brand": pair[f"brand_side{side}"], "product": pair["product"], "line": pair[f"side{side}"]}
        if row[f"brand_{letter}"] != parts[letter]["brand"] or row[f"{letter}_is"] != pair[f"side{side}_label"]:
            raise ValueError("Brand/side label disagrees with pair")
    expected = INSTRUCTIONS[row["condition"]] + "Order one of these for me:\n"
    expected += "\n".join(f"{a}) {p['brand']} {p['product']}, {p['line']}." for a, p in parts.items())
    expected += "\nAnswer with A or B."
    if row["prompt"] != expected:
        raise ValueError("Prompt text differs from exact canonical frame")
    return parts


def verify_template(tokenizer):
    if not tokenizer.is_fast:
        raise ValueError("Fast tokenizer required for offsets")
    template = tokenizer.get_chat_template()
    if hashlib.sha256(template.encode()).hexdigest() != TEMPLATE_SHA:
        raise ValueError("Chat template SHA differs: STOP")


def token_span(text, ids, offsets, start, end, tokenizer, *, whitespace_boundary=False):
    indices = [i for i, (a, b) in enumerate(offsets) if b > a and a < end and b > start]
    if not indices or indices != list(range(indices[0], indices[-1] + 1)):
        raise ValueError("Empty/non-contiguous token span")
    a, b = offsets[indices[0]][0], offsets[indices[-1]][1]
    if a > start or b < end:
        raise ValueError("Incomplete character coverage")
    left, right = text[a:start], text[end:b]
    decoded = tokenizer.decode([ids[i] for i in indices], skip_special_tokens=False, clean_up_tokenization_spaces=False)
    # Explicit policy, never silently strip token boundaries.
    if decoded != text[a:b]:
        raise ValueError("Decoded token span does not match rendered characters")
    if left or right:
        if not whitespace_boundary or left not in ("", " ") or right:
            raise ValueError("Token boundary overhang: exact text cannot be decoded without extra characters")
    return {"char_start": start, "char_end": end, "token_indices": indices,
            "text": text[start:end], "decoded": decoded, "left_overhang": left, "right_overhang": right}


def prepare(row, pair, tokenizer, *, whitespace_boundary=False):
    parts = option_parts(row, pair)
    verify_template(tokenizer)
    messages = [{"role": "user", "content": row["prompt"]}]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    if rendered.count(row["prompt"]) != 1:
        raise ValueError("User text not preserved uniquely in rendering")
    encoded = tokenizer(rendered, add_special_tokens=False, return_offsets_mapping=True)
    ids, offsets = list(encoded["input_ids"]), [tuple(x) for x in encoded["offset_mapping"]]
    templated_ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False)
    # Transformers 5.14 returns BatchEncoding by default, unlike older list API.
    if isinstance(templated_ids, Mapping):
        templated_ids = templated_ids["input_ids"]
    if ids != list(templated_ids) or len(ids) != len(offsets):
        raise ValueError("Rendered and template token IDs disagree")
    base = rendered.index(row["prompt"])
    spans = {}
    for letter, p in parts.items():
        prefix = f"{letter}) {p['brand']} {p['product']}, "
        start = base + row["prompt"].index(prefix)
        brand_start = start + len(letter + ") ")
        product_start = brand_start + len(p["brand"]) + 1
        line_start = start + len(prefix)
        for name, a in (("brand", brand_start), ("product", product_start), ("line", line_start)):
            spans[letter + "_" + name] = token_span(rendered, ids, offsets, a, a + len(p[name]), tokenizer,
                                                    whitespace_boundary=whitespace_boundary)
    pos = {"endA": spans["A_line"]["token_indices"][-1], "endB": spans["B_line"]["token_indices"][-1],
           "meanA": spans["A_line"]["token_indices"], "meanB": spans["B_line"]["token_indices"], "final": len(ids) - 1}
    if not pos["endA"] < pos["endB"] < pos["final"]:
        raise ValueError("Position ordering failure")
    return {**row, "rendered": rendered, "input_ids": ids, "offset_mapping": offsets,
            "spans": spans, "positions": pos, "boundary_policy": "single-leading-ASCII-space" if whitespace_boundary else "exact"}


def candidates(tokenizer):
    out = []
    for prefix in ("", " ", "\n"):
        for label in ("A", "B"):
            text = prefix + label
            ids = list(tokenizer.encode(text, add_special_tokens=False))
            if not ids:
                raise ValueError("Empty answer tokenization")
            out.append({"text": text, "label": label, "prefix": prefix, "ids": ids,
                        "single_token": len(ids) == 1, "candidate_id": ids[0]})
    return out


def calibrated_family(records, token_candidates):
    families = []
    eligible = set()
    for prefix in ("", " ", "\n"):
        ids = {c["label"]: c["candidate_id"] for c in token_candidates if c["prefix"] == prefix and c["single_token"]}
        if set(ids) == {"A", "B"} and ids["A"] != ids["B"]:
            eligible.add(prefix)
    all_families = []
    for record in records:
        first = record["greedy_ids"][0]
        matches = [c for c in token_candidates if c["single_token"] and c["candidate_id"] == first]
        if matches:
            all_families.append(matches[0]["prefix"])
            symmetric = [c for c in matches if c["prefix"] in eligible]
            if symmetric:
                families.append(symmetric[0]["prefix"])
    if not families:
        raise ValueError("Calibration has no recognized single-token answer family")
    counts = Counter(families)
    # Prospective modal-family rule; ties resolved raw, space, newline, never by
    # behavioural accuracy or labels. Both A and B always use the same prefix.
    family = max(eligible, key=lambda p: (counts[p], -("", " ", "\n").index(p)))
    selected = {c["label"]: c["candidate_id"] for c in token_candidates if c["prefix"] == family and c["single_token"]}
    if set(selected) != {"A", "B"} or selected["A"] == selected["B"]:
        raise ValueError("A/B calibration does not identify distinct single-token candidates")
    return {"prefix": family, "ids": selected, "off_format": len(records) - len(all_families), "n": len(records),
            "all_family_counts": dict(Counter(all_families)), "symmetric_families": sorted(eligible),
            "family_counts": dict(counts), "mixed_families": len(counts) > 1,
            "tie": sum(v == counts[family] for v in counts.values()) > 1,
            "rule": "modal recognized first-token prefix; ties raw, space, newline; symmetric A/B"}


def sample_indices(n, count, seed=SEED):
    if n < count:
        raise ValueError("Insufficient prompts for fixed sample")
    return sorted(random.Random(seed).sample(range(n), count))


def cpu_sample(rows, pairs):
    """Thirty deterministic prompts, covering 9 cells and required edge cases."""
    chosen = set()
    for subset in sorted({r["set"] for r in rows}):
        for condition in INSTRUCTIONS:
            chosen.add(next(i for i, r in enumerate(rows) if r["set"] == subset and r["condition"] == condition))
    chosen.add(max(range(len(rows)), key=lambda i: max(len(rows[i]["brand_A"]), len(rows[i]["brand_B"]))))
    for predicate in (lambda s: len(s.split()) == 5, lambda s: len(s.split()) == 10):
        matches = [i for i, r in enumerate(rows) if any(predicate(pairs[r["pair_id"]][f"side{k}"]) for k in (1, 2))]
        if not matches:
            raise ValueError("Required CPU edge case absent")
        chosen.add(matches[0])
    pool = list(range(len(rows)))
    random.Random(SEED).shuffle(pool)
    for i in pool:
        if len(chosen) == 30:
            break
        chosen.add(i)
    return sorted(chosen)


def numeric_fixture(row, pair):
    """Clearly synthetic CPU offset case; never supplied to the extraction worker."""
    p = dict(pair, pair_id="synthetic_cpu_numeric_ending", side1="birds remain in holding area 10",
             side2="birds remain in holding area 20")
    r = dict(row, pair_id=p["pair_id"], prompt_id="synthetic_cpu_numeric_ending", condition="none")
    first = 1 if p["side1_is_A_in_original"] != r["mirrored"] else 2
    r["prompt"] = "Order one of these for me:\n" + "\n".join(
        f"{a}) {p[f'brand_side{k}']} {p['product']}, {p[f'side{k}']}." for a, k in (("A", first), ("B", 3-first))) + "\nAnswer with A or B."
    return r, p


def import_audited(path):
    """Import unchanged module; its historical mkdir calls become no-ops only.

    This narrow import-time shim is recorded in runtime provenance. No original
    paths are created or modified, and no audited function body is rewritten.
    """
    from unittest.mock import patch
    spec = importlib.util.spec_from_file_location("minimal_pairs_audited_rq2", path)
    module = importlib.util.module_from_spec(spec)
    with patch("os.makedirs", lambda *args, **kwargs: None):
        spec.loader.exec_module(module)
    return module


def forward(prepared, model, helper):
    import numpy as np
    pos = prepared["positions"]
    selected = sorted(set([pos["endA"], pos["endB"], pos["final"]] + pos["meanA"] + pos["meanB"]))
    states, logits = helper.extract_hidden_states_for_positions(model, prepared["input_ids"], selected)
    if states.ndim != 3 or states.shape[1] != 32 or states.shape[0] != len(selected):
        raise ValueError("Expected all 32 residual layers, not embeddings or a layer subset")
    lookup = {token: i for i, token in enumerate(selected)}
    values = []
    for name in POSITIONS:
        tokens = pos[name] if isinstance(pos[name], list) else [pos[name]]
        # Audited helper returns fp16 token states. Accumulate their means in fp32.
        values.append(states[[lookup[t] for t in tokens]].astype(np.float32).mean(axis=0).astype(np.float16))
    array = np.stack(values)
    final_logits = logits[pos["final"]].detach().float().cpu().numpy()
    if not np.isfinite(array).all() or not np.isfinite(final_logits).all():
        raise ValueError("Nonfinite extraction")
    return array, final_logits


@contextmanager
def lock(root):
    path = root / "worker.lock"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, json.dumps({"pid": os.getpid(), "started": time.time()}).encode())
    os.fsync(fd)
    os.close(fd)
    try:
        yield
    finally:
        path.unlink()


def verify_snapshot(snapshot, manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest["revision"] != REVISION or manifest["model_id"] != "Qwen/Qwen3.5-9B":
        raise ValueError("Snapshot model identity differs")
    snapshot = Path(snapshot).resolve()
    actual = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()}
    expected = set(manifest["files"])
    if actual != expected:
        raise ValueError("Snapshot file inventory differs; include every local model/tokenizer file")
    for relative, expected_hash in manifest["files"].items():
        lexical = snapshot / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Unsafe snapshot-relative path")
        path = lexical.resolve()
        cache_blobs = snapshot.parent.parent / "blobs"
        cache_link = (snapshot.parent.name == "snapshots" and snapshot.name == REVISION
                      and snapshot.parent.parent.name == "models--Qwen--Qwen3.5-9B"
                      and lexical.is_symlink() and path.is_relative_to(cache_blobs.resolve()))
        if (not path.is_relative_to(snapshot) and not cache_link) or sha(path) != expected_hash:
            raise ValueError("Snapshot hash/path mismatch")
    return manifest


def load_qwen_conditional_adapter(snapshot, config):
    """Named compatibility adapter; no global factory patches or helper edits.

    Qwen3.5's pinned architecture can require the conditional-generation class
    instead of AutoModelForCausalLM. Use only that exact audited model identity.
    """
    import torch
    from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration
    if config.architectures != ["Qwen3_5ForConditionalGeneration"]:
        raise ValueError("Unexpected architecture; conditional adapter refused")
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
    model = Qwen3_5ForConditionalGeneration.from_pretrained(snapshot, config=config,
            dtype=torch.bfloat16, device_map="auto", local_files_only=True)
    model.eval()
    return model, tokenizer


def load_runtime(args):
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import numpy as np
    import torch
    import transformers
    expected_versions = {"torch": "2.11.0", "transformers": "5.14.1", "numpy": "2.4.6"}
    actual_versions = {"torch": torch.__version__, "transformers": transformers.__version__, "numpy": np.__version__}
    if any(actual_versions[k].split("+")[0] != v for k, v in expected_versions.items()):
        raise RuntimeError(f"Pinned runtime version mismatch: {actual_versions}")
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("CUDA bf16 required; audited loader fp16 fallback forbidden")
    verify_snapshot(args.snapshot, args.snapshot_manifest)
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    helper = import_audited(args.helper)
    snapshot = str(Path(args.snapshot).resolve())
    config = transformers.AutoConfig.from_pretrained(snapshot, local_files_only=True)
    if type(config) in transformers.AutoModelForCausalLM._model_mapping:
        model, tokenizer = helper.load_qwen_model_and_tokenizer(snapshot)
        loader = "unchanged audited load_qwen_model_and_tokenizer; verified local snapshot"
    else:
        model, tokenizer = load_qwen_conditional_adapter(snapshot, config)
        loader = "named load_qwen_conditional_adapter; audited AutoModelForCausalLM mapping incompatible"
    model.eval()
    if any(p.is_floating_point() and p.dtype != torch.bfloat16 for p in model.parameters()):
        raise RuntimeError("Audited loader did not produce exclusively bf16 floating parameters")
    verify_template(tokenizer)
    module_file = inspect.getfile(type(model))
    return model, tokenizer, helper, {"torch": torch.__version__, "transformers": transformers.__version__,
        "numpy": np.__version__, "model_revision": REVISION, "template_sha256": TEMPLATE_SHA,
        "helper_sha256": sha(args.helper), "script_sha256": sha(__file__), "seed": SEED,
        "import_shim": "suppress import-time os.makedirs only", "loader": loader, "device": torch.cuda.get_device_name(),
        "mean_policy": "fp32 mean of audited fp16 token states then fp16 storage",
        "hidden_states_identity": "literal output.hidden_states[1:]; layers1-31 decoder outputs; layer32 post-final-norm, not raw block output",
        "hidden_states_source_evidence": "transformers5.14.1 modeling_qwen3_5.py capture_outputs at1158,norm at1222; utils/output_capturing.py tie_last_hidden_states default True at223-226, last_hidden_state replacement at275-277",
        "model_class": type(model).__name__, "model_module_source_sha256": sha(module_file),
        "module_mapping": [{"name": n, "class": type(mod).__name__} for n, mod in model.named_modules()
                           if n.endswith("norm") or n.rsplit(".", 1)[-1].isdigit()],
        "layer32_causal_caveat": "Final hidden state has no downstream inter-token mixing; no causal eligibility or post-result layer substitution implied",
        "attention_implementation": getattr(model.config, "_attn_implementation", None)}


def validate_recovery(root, rows, identity):
    """Check all durable state before loading any weights or making a forward."""
    events = [json.loads(s) for s in (root / "ledger.jsonl").read_text().splitlines()] if (root / "ledger.jsonl").exists() else []
    keys = set()
    for event in events:
        if event.get("phase") == "worker" and event.get("state") == "complete":
            continue
        key = (event.get("phase"), event.get("row"), event.get("state"))
        if key in keys or key[0] not in ("main", "integrity") or key[2] not in ("intent", "complete"):
            raise ValueError("Unknown/duplicate ledger event")
        if type(key[1]) is not int or not 0 <= key[1] < len(rows):
            raise ValueError("Out-of-range ledger row")
        if key[0] == "integrity" and key[1] not in identity["integrity_indices"]:
            raise ValueError("Unexpected integrity sample row")
        keys.add(key)
    completed = {e["row"]: e for e in events if e.get("phase") == "main" and e.get("state") == "complete"}
    integrity_done = {e["row"]: e for e in events if e.get("phase") == "integrity" and e.get("state") == "complete"}
    for i, row in enumerate(rows):
        base = root / "shards" / f"{i:04d}"
        marker, array, intent = (base.with_suffix(s) for s in (".json", ".npz", ".intent"))
        if not marker.exists():
            if intent.exists() or array.exists() or i in completed or ("main", i, "intent") in keys:
                raise RuntimeError(f"Uncertain attempt {i}; inspect without loading backend")
            continue
        if not intent.exists() or not array.exists() or i not in completed or ("main", i, "intent") not in keys:
            raise RuntimeError(f"Incomplete durable record {i}; inspect without loading backend")
        record = json.loads(marker.read_text(encoding="utf-8"))
        attempt = json.loads(intent.read_text())
        input_path = root / "shards" / f"{i:04d}.input.json"
        if not input_path.exists():
            raise ValueError("Completed attempt missing saved pre-forward input")
        original_fields = {k: v for k, v in record.items() if k in set(row) | {"rendered", "input_ids", "offset_mapping", "spans", "positions", "boundary_policy"}}
        if (record["prompt_id"] != row["prompt_id"] or attempt["input_sha256"] != digest(original_fields)
                or json.loads(input_path.read_text(encoding="utf-8")) != original_fields
                or any(record[k] != v for k, v in row.items()) or sha(marker) != completed[i]["sha256"]
                or record["array_sha256"] != sha(array)):
            raise ValueError(f"Completed shard provenance mismatch {i}")
    for i in identity["integrity_indices"]:
        marker, intent = root / f"integrity_{i:04d}.json", root / f"integrity_{i:04d}.intent"
        if intent.exists() and not marker.exists():
            raise RuntimeError("Uncertain integrity attempt; inspect before loading backend")
        if marker.exists():
            main_marker = root / "shards" / f"{i:04d}.json"
            if (not intent.exists() or i not in integrity_done or not main_marker.exists()
                    or sha(marker) != integrity_done[i]["sha256"]
                    or json.loads(intent.read_text())["main_record_sha256"] != sha(main_marker)):
                raise ValueError("Integrity record provenance mismatch")
            check = json.loads(marker.read_text())
            main = json.loads(main_marker.read_text(encoding="utf-8"))
            candidate_ids = sorted({c["candidate_id"] for c in main["candidate_tokens"]})
            if (check["row"] != i or json.loads(intent.read_text())["row"] != i
                    or check["original"] != [main["candidate_logits"][str(k)] for k in candidate_ids]
                    or ("integrity", i, "intent") not in keys):
                raise ValueError("Integrity output row/logits binding mismatch")


def greedy_tail(model, first, ids):
    """Reuse main-pass first token; only two additional forwards, no cache."""
    import torch
    device = next(model.parameters()).device
    generated = [int(first)]
    for _ in range(2):
        with torch.no_grad():
            out = model(input_ids=torch.tensor([ids + generated], device=device), use_cache=False, output_hidden_states=False)
        generated.append(int(out.logits[0, -1].argmax().item()))
    return generated


def worker(args):
    import numpy as np
    if not args.free_runtime_confirmed:
        raise RuntimeError("Task-specific explicit free-runtime confirmation required")
    rows, pairs = load_data(args.prompts, args.pairs)
    root = Path(args.output)
    if not root.exists():
        root.mkdir(parents=True)
    elif not args.resume:
        raise FileExistsError("Output exists; never overwrite or implicitly resume")
    identity = {"prompts": sha(args.prompts), "pairs": sha(args.pairs), "script": sha(__file__),
                "helper": sha(args.helper), "snapshot_manifest": sha(args.snapshot_manifest),
                "boundary_policy": args.whitespace_boundary, "seed": SEED,
                "calibration_indices": sample_indices(len(rows), 30), "integrity_indices": sample_indices(len(rows), 20)}
    with lock(root):
        if (root / "identity.json").exists():
            if json.loads((root / "identity.json").read_text()) != identity:
                raise ValueError("Resume identity mismatch")
        else:
            write_json(root / "identity.json", identity)
        if (root / "COMPLETE.json").exists():
            raise RuntimeError("Run already complete")
        validate_recovery(root, rows, identity)
        model, tokenizer, helper, environment = load_runtime(args)
        if (root / "environment.json").exists():
            if json.loads((root / "environment.json").read_text()) != environment:
                raise ValueError("Runtime changed on resume")
        else:
            write_json(root / "environment.json", environment)
        token_candidates = candidates(tokenizer)
        candidate_ids = sorted({c["candidate_id"] for c in token_candidates})
        shards = root / "shards"
        shards.mkdir(exist_ok=True)
        for i, row in enumerate(rows):
            marker, array_path, intent = (shards / f"{i:04d}{suffix}" for suffix in (".json", ".npz", ".intent"))
            if marker.exists():
                saved = json.loads(marker.read_text())
                if saved["prompt_id"] != row["prompt_id"] or saved["array_sha256"] != sha(array_path):
                    raise ValueError("Completed shard integrity failed")
                continue
            if intent.exists() or array_path.exists():
                raise RuntimeError(f"Uncertain attempt {i}; preserve and report, never retry")
            prepared = prepare(row, pairs[row["pair_id"]], tokenizer, whitespace_boundary=args.whitespace_boundary)
            input_path = shards / f"{i:04d}.input.json"
            if input_path.exists():
                if json.loads(input_path.read_text(encoding="utf-8")) != json.loads(json.dumps(prepared)):
                    raise ValueError("Saved pre-forward input mismatch")
            else:
                write_json(input_path, prepared)
            write_json(intent, {"prompt_id": row["prompt_id"], "input_sha256": digest(prepared), "pid": os.getpid()})
            append_event(root, phase="main", row=i, state="intent")
            states, logits = forward(prepared, model, helper)
            prepared.update(candidate_tokens=token_candidates, candidate_logits={str(k): float(logits[k]) for k in candidate_ids},
                            greedy_first_id=int(logits.argmax()))
            if i in identity["calibration_indices"]:
                generated = greedy_tail(model, logits.argmax(), prepared["input_ids"])
                prepared.update(greedy_ids=generated, greedy_text=tokenizer.decode(generated, skip_special_tokens=False))
            with array_path.open("xb") as f:
                np.savez(f, activations=states)
                f.flush()
                os.fsync(f.fileno())
            prepared["array_sha256"] = sha(array_path)
            write_json(marker, prepared)
            append_event(root, phase="main", row=i, state="complete", sha256=sha(marker))
            write_json(root / "progress.json", {"completed": i + 1, "total": len(rows)}, exclusive=False)
            print(json.dumps({"completed": i + 1, "total": len(rows)}), flush=True)
        records = [json.loads((shards / f"{i:04d}.json").read_text(encoding="utf-8")) for i in range(len(rows))]
        calibration_records = [records[i] for i in identity["calibration_indices"]]
        family = calibrated_family(calibration_records, token_candidates)
        calibration = {**family, "indices": identity["calibration_indices"], "records": calibration_records}
        if not (root / "calibration.json").exists():
            write_json(root / "calibration.json", calibration)
        elif json.loads((root / "calibration.json").read_text(encoding="utf-8")) != calibration:
            raise ValueError("Calibration record differs from hashed main records")
        a_id, b_id = family["ids"]["A"], family["ids"]["B"]
        integrity = []
        for i in identity["integrity_indices"]:
            marker, intent = root / f"integrity_{i:04d}.json", root / f"integrity_{i:04d}.intent"
            if marker.exists():
                integrity.append(json.loads(marker.read_text()))
                continue
            if intent.exists():
                raise RuntimeError("Uncertain integrity attempt; do not retry")
            write_json(intent, {"row": i, "main_record_sha256": sha(shards / f"{i:04d}.json")})
            append_event(root, phase="integrity", row=i, state="intent")
            _, logits = forward(records[i], model, helper)
            check = {"row": i, "original": [records[i]["candidate_logits"][str(k)] for k in candidate_ids],
                     "recomputed": [float(logits[k]) for k in candidate_ids],
                     "same_greedy": int(logits.argmax()) == records[i]["greedy_first_id"],
                     "same_choice": (float(logits[a_id]) > float(logits[b_id])) ==
                         (records[i]["candidate_logits"][str(a_id)] > records[i]["candidate_logits"][str(b_id)])}
            write_json(marker, check)
            append_event(root, phase="integrity", row=i, state="complete", sha256=sha(marker))
            integrity.append(check)
        corr = float(np.corrcoef(np.array([r["original"] for r in integrity]).ravel(),
                                 np.array([r["recomputed"] for r in integrity]).ravel())[0, 1])
        passed = np.isfinite(corr) and corr > .999 and all(r["same_choice"] and r["same_greedy"] for r in integrity)
        if not (root / "integrity.json").exists():
            write_json(root / "integrity.json", {"correlation": corr if np.isfinite(corr) else None, "passed": bool(passed), "checks": integrity})
        if not passed:
            raise RuntimeError("Integrity gate failed: STOP")
        # Partial consolidation requires inspected manual recovery; it never
        # permits a new model attempt or silent overwrite of an existing layer.
        for layer in range(32):
            target = root / f"layer_{layer + 1:02d}.npz"
            if target.exists():
                raise RuntimeError("Partial consolidation exists; inspect before recovery")
            values = np.stack([np.load(shards / f"{i:04d}.npz")["activations"][:, layer, :] for i in range(len(rows))])
            with target.open("xb") as f:
                np.savez(f, activations=values, positions=np.array(POSITIONS), layer=np.array(layer + 1))
        with (root / "index.jsonl").open("x", encoding="utf-8", newline="\n") as f:
            for r in records:
                gap = r["candidate_logits"][str(a_id)] - r["candidate_logits"][str(b_id)]
                pa = float(1 / (1 + np.exp(-np.clip(gap, -700, 700))))
                f.write(json.dumps({**r, "choice_score": gap, "p_A": pa, "answer_token_ids": family["ids"]}, ensure_ascii=False) + "\n")
        append_event(root, phase="worker", state="complete")
        files = {p.relative_to(root).as_posix(): sha(p) for p in root.rglob("*") if p.is_file() and p.name != "worker.lock"}
        valid_answer_ids = {c["candidate_id"] for c in token_candidates if c["single_token"]}
        write_json(root / "COMPLETE.json", {"files": files, "rows": len(rows), "layers": 32, "positions": POSITIONS,
                   "off_format_first_tokens": sum(r["greedy_first_id"] not in valid_answer_ids for r in records),
                   "other_valid_answer_family_first_tokens": sum(r["greedy_first_id"] in valid_answer_ids
                                                                   and r["greedy_first_id"] not in (a_id, b_id) for r in records),
                   "integrity_passed": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preflight", "worker"])
    parser.add_argument("--prompts", required=True)
    parser.add_argument("--pairs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tokenizer")
    parser.add_argument("--snapshot")
    parser.add_argument("--snapshot-manifest")
    parser.add_argument("--helper", default=str(Path(__file__).resolve().parents[1] / "rq2/run_rq2_gpu_pipeline.py"))
    parser.add_argument("--whitespace-boundary", action="store_true", help="Explicit reviewed whitespace-only BPE overhang policy")
    parser.add_argument("--free-runtime-confirmed", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.mode == "worker":
        if not args.snapshot or not args.snapshot_manifest:
            parser.error("worker requires local snapshot and hash manifest")
        worker(args)
        return
    if not args.tokenizer:
        parser.error("preflight requires local tokenizer directory")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    rows, pairs = load_data(args.prompts, args.pairs)
    prepared = [prepare(row, pairs[row["pair_id"]], tokenizer, whitespace_boundary=args.whitespace_boundary) for row in rows]
    sample = cpu_sample(rows, pairs)
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    with (root / "rendered.jsonl").open("x", encoding="utf-8") as f:
        for record in prepared:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    decoded = []
    for i in sample:
        r = prepared[i]
        positions = {name: tokenizer.decode([r["input_ids"][t] for t in (pos if isinstance(pos, list) else [pos])],
                                            clean_up_tokenization_spaces=False) for name, pos in r["positions"].items()}
        decoded.append({"row": i, "prompt_id": r["prompt_id"], "decoded_positions": positions, "spans": r["spans"]})
        print(json.dumps(decoded[-1], ensure_ascii=False))
    synthetic_row, synthetic_pair = numeric_fixture(rows[0], pairs[rows[0]["pair_id"]])
    synthetic = prepare(synthetic_row, synthetic_pair, tokenizer, whitespace_boundary=args.whitespace_boundary)
    print(json.dumps({"synthetic_cpu_only": True, "numeric_ending": synthetic}, ensure_ascii=False))
    write_json(root / "preflight.json", {"prompts": len(rows), "pairs": len(pairs), "sample": decoded,
                "synthetic_numeric_ending_cpu_only": synthetic,
                "candidates": candidates(tokenizer), "seed": SEED, "template_sha256": TEMPLATE_SHA,
                "sources": {"prompts": sha(args.prompts), "pairs": sha(args.pairs), "script": sha(__file__)},
                "rendered_sha256": sha(root / "rendered.jsonl")})


if __name__ == "__main__":
    main()
