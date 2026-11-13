"""Offline one-attempt runner. Importing this module never loads a model.

run_prepared is suitable for an explicitly authorized durable notebook cell.
No CLI auto-run, network, retries, chat rendering, or tool execution.
"""
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from collections import Counter
import dataclasses

REVISION = 'c202236235762e1c871ad0ccb60c8ee5ba337b9a'
SEED = 20261114
VERSIONS = {'vllm': '0.24.0', 'torch': '2.11.0', 'transformers': '5.14.1', 'numpy': '2.4.6'}
ENGINE = dict(dtype='bfloat16', quantization=None, enforce_eager=True, enable_prefix_caching=False,
              max_model_len=6710, max_num_seqs=1, gpu_memory_utilization=0.5,
              tensor_parallel_size=1, seed=SEED, generation_config='vllm',
              disable_log_stats=True, limit_mm_per_prompt={'image': 0, 'video': 0})
SAMPLING = dict(temperature=0.0, top_p=1.0, top_k=-1, min_p=0.0,
                repetition_penalty=1.0, presence_penalty=0.0, frequency_penalty=0.0,
                seed=SEED, n=1, max_tokens=256, min_tokens=0, ignore_eos=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def jsha(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')).encode())


def read_bundle(manifest_path, expected_manifest_sha256):
    """Strict v1 manifest plus gzip JSON list of prepared job records."""
    path = Path(manifest_path).resolve()
    raw = path.read_bytes()
    if sha(raw) != expected_manifest_sha256:
        raise ValueError('Manifest hash mismatch')
    manifest = json.loads(raw)
    if manifest['runner_sha256'] != file_sha(__file__):
        raise ValueError('Runner bytes differ from frozen manifest')
    if manifest['schema'] != 'capacity_runner_v1' or manifest['model_revision'] != REVISION:
        raise ValueError('Wrong schema or model revision')
    for key, actual in [('engine', ENGINE), ('sampling', SAMPLING)]:
        if manifest[key] != actual:
            raise ValueError('Frozen configuration mismatch: ' + key)
    bundle = (path.parent / manifest['prepared_file']).resolve()
    if not bundle.is_relative_to(path.parent):
        raise ValueError('Prepared input path escapes manifest directory')
    raw = bundle.read_bytes()
    if sha(raw) != manifest['prepared_sha256']:
        raise ValueError('Prepared gzip hash mismatch')
    jobs = json.loads(gzip.decompress(raw))
    if not isinstance(jobs, list) or len(jobs) != manifest['job_count']:
        raise ValueError('Prepared job count mismatch')
    expected = manifest['jobs']
    seen = set()
    for job in jobs:
        jid = job['job_id']
        if not isinstance(jid, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', jid) or jid in seen:
            raise ValueError('Invalid or duplicate job ID')
        seen.add(jid)
        ids = job['input_ids']
        if not ids or any(type(x) is not int or x < 0 for x in ids) or len(ids)+256 > 6710:
            raise ValueError('Invalid input token IDs or length')
        if jsha(ids) != job['input_ids_json_sha256'] or jsha(job) != expected[jid]:
            raise ValueError('Prepared job/hash mismatch')
        if job.get('historical_reasoning_omission_flag') or not job.get('base_token_prefix_preserved', False):
            raise ValueError('Input contract failure')
    if seen != set(expected):
        raise ValueError('Manifest coverage mismatch')
    return manifest, jobs


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    # Persist directory entry on platforms that support directory fsync.
    if os.name != 'nt':
        fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def append_event(path, event):
    with Path(path).open('a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())


def preserve_environment(path, environment):
    """Never replace provenance from the first session with resumed hardware."""
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != environment:
            raise ValueError('Resume runtime environment differs from original session')
    else:
        atomic_json(path, environment)


def serialize_output(output, job):
    ids = list(output.prompt_token_ids)
    candidates = [dict(text=o.text, token_ids=list(o.token_ids),
                       finish_reason=o.finish_reason, stop_reason=o.stop_reason,
                       cumulative_logprob=getattr(o, 'cumulative_logprob', None))
                  for o in output.outputs]
    match = ids == job['input_ids']
    if not match:
        completion = 'input_contract_failure'
    elif len(candidates) != 1:
        completion = 'malformed_or_ambiguous'
    elif candidates[0]['finish_reason'] == 'length':
        completion = 'token_limit_truncated'
    elif candidates[0]['finish_reason'] != 'stop':
        completion = 'generation_failure'
    elif not candidates[0]['text'].strip():
        completion = 'no_final_answer'
    elif any(s in candidates[0]['text'] for s in ('<think>', '</think>', '<tool_call>')):
        completion = 'malformed_or_ambiguous'
    else:
        completion = 'complete'  # Semantic/yes-no scoring remains a separate step.
    return dict(job_id=job['job_id'], backend_request_id=str(output.request_id),
                prompt_token_ids=ids, input_ids_equal=match, outputs=candidates,
                completion=completion)


def run_jobs(jobs, output_dir, frozen_identity, generate_one, prepare=None):
    """Durable sequential core; generate_one(ids) returns one RequestOutput.

    Existing intent without a response is uncertain and BLOCKS resume. An atomic
    response without completion event is recovered without another generation.
    A lock is intentionally retained after hard process death for manual audit.
    """
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / 'RUNNING.lock'
    fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        identity_path = root / 'identity.json'
        if identity_path.exists():
            if json.loads(identity_path.read_text(encoding='utf-8')) != frozen_identity:
                raise ValueError('Resume identity mismatch')
        else:
            atomic_json(identity_path, frozen_identity)
        ledger = root / 'ledger.jsonl'
        events = [json.loads(s) for s in ledger.read_text(encoding='utf-8').splitlines()] if ledger.exists() else []
        known = {j['job_id']: j for j in jobs}
        state = {}
        for e in events:
            jid = e['job_id']
            if jid not in known or e['input_hash'] != jsha(known[jid]['input_ids']):
                raise ValueError('Ledger does not match frozen jobs')
            if e['event'] == 'intent':
                if jid in state:
                    raise ValueError('Duplicate intent')
            elif e['event'] == 'completion':
                if state.get(jid, {}).get('event') != 'intent':
                    raise ValueError('Completion without single intent')
            else:
                raise ValueError('Unknown ledger event')
            state[jid] = e
        results = []
        # Reconcile all old intents before allowing any new model invocation.
        for jid, e in state.items():
            response = root / (jid + '.json')
            if not response.exists():
                raise RuntimeError('Uncertain intent or missing response; never retry: ' + jid)
            raw = response.read_bytes()
            r = json.loads(raw)
            if r['job_id'] != jid or r['input_hash'] != e['input_hash'] or r['request_id'] != e['request_id']:
                raise ValueError('Response identity mismatch')
            if e['event'] == 'completion' and e['response_sha256'] != sha(raw):
                raise ValueError('Stored response changed')
            if e['event'] == 'intent':
                append_event(ledger, dict(e, event='completion', response_sha256=sha(raw), recovered=True))
            results.append(r)
        def progress():
            summary = dict(total=len(jobs), completed=len(results),
                           remaining=len(jobs)-len(results),
                           completion_counts=dict(Counter(r['completion'] for r in results)))
            atomic_json(root / 'summary.json', summary)
            if len(results) % 25 == 0 or len(results) == len(jobs):
                print('CAPACITY_PROGRESS ' + json.dumps(summary, sort_keys=True), flush=True)
        progress()
        # Engineering startup occurs under lock AFTER full ledger recovery, but
        # BEFORE any new intent. Startup failure consumes zero study attempts.
        pending = [j for j in jobs if j['job_id'] not in state]
        for j in pending:
            if (root / (j['job_id'] + '.json')).exists():
                raise RuntimeError('Orphan response requires audit: ' + j['job_id'])
        if pending and prepare is not None:
            prepare()
        for job in jobs:
            jid = job['job_id']
            if jid in state:
                continue
            response = root / (jid + '.json')
            if response.exists():
                raise RuntimeError('Orphan response requires audit: ' + jid)
            intent = dict(event='intent', job_id=jid, input_hash=jsha(job['input_ids']),
                          request_id=uuid.uuid4().hex, time=time.time())
            append_event(ledger, intent)  # Durable BEFORE dispatch.
            try:
                r = serialize_output(generate_one(list(job['input_ids'])), job)
            except Exception as exc:
                r = dict(job_id=jid, completion='generation_failure',
                         error_type=type(exc).__name__, error=str(exc))
            r.update(input_hash=intent['input_hash'], request_id=intent['request_id'])
            atomic_json(response, r)
            append_event(ledger, dict(intent, event='completion', response_sha256=sha(response.read_bytes())))
            results.append(r)
            progress()
            if r['completion'] in ('generation_failure', 'input_contract_failure'):
                raise RuntimeError('Stopped after persisted failure; failed job will not retry: ' + jid)
        return results
    finally:
        lock.unlink()


def make_backend(manifest, local_model_path, environment_path):
    """Execution boundary; native sampler flag matches prior fidelity retry."""
    model = Path(local_model_path).resolve()
    if not model.is_dir() or model.name != REVISION:
        raise ValueError('Require pinned local snapshot directory')
    for rel, digest in manifest['model_files'].items():
        relative = Path(rel)
        file = model / relative
        # HF snapshot files may be symlinks into sibling blobs; hash their bytes.
        if relative.is_absolute() or '..' in relative.parts or file_sha(file) != digest:
            raise ValueError('Pinned model file mismatch: ' + rel)
    if not manifest['model_files']:
        raise ValueError('Require frozen model file hashes')
    if 'vllm' in sys.modules and os.environ.get('VLLM_USE_FLASHINFER_SAMPLER') != '0':
        raise RuntimeError('vLLM already imported before native sampler selection')
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_DATASETS_OFFLINE='1', VLLM_WORKER_MULTIPROC_METHOD='spawn',
                      VLLM_USE_FLASHINFER_SAMPLER='0')
    versions = {name: importlib.metadata.version(name) for name in VERSIONS}
    if versions != VERSIONS:
        raise ValueError('Dependency version mismatch: ' + repr(versions))
    if manifest['sampler'] != {'name': 'pytorch_native', 'VLLM_USE_FLASHINFER_SAMPLER': '0'}:
        raise ValueError('Native sampler configuration mismatch')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(model), local_files_only=True, trust_remote_code=False)
    end = tokenizer.convert_tokens_to_ids('<|im_end|>')
    eos = tokenizer.eos_token_id
    if type(end) is not int or type(eos) is not int or tokenizer.convert_ids_to_tokens(end) != '<|im_end|>':
        raise ValueError('Cannot resolve pinned stop tokens')
    stops = sorted({end, eos})
    if stops != manifest['stop_token_ids']:
        raise ValueError('Stop tokens differ from frozen tokenizer')
    from vllm import LLM, SamplingParams
    llm = LLM(model=str(model), tokenizer=str(model), trust_remote_code=False, **ENGINE)
    params = SamplingParams(stop_token_ids=stops, **SAMPLING)
    import torch
    engine_config = llm.llm_engine.vllm_config
    attention = getattr(engine_config, 'attention_config', None)
    attention_record = (dataclasses.asdict(attention) if dataclasses.is_dataclass(attention)
                        else (None if attention is None else repr(attention)))
    # Convert enums/types to stable strings while preserving JSON values.
    attention_record = json.loads(json.dumps(attention_record, default=str))
    # Record resolved runtime configuration, not merely requested kwargs.
    resolved = {
        'model': {key: str(getattr(engine_config.model_config, key)) for key in
                  ('model', 'tokenizer', 'dtype', 'max_model_len', 'enforce_eager', 'seed')},
        'cache': {key: getattr(engine_config.cache_config, key) for key in
                  ('enable_prefix_caching', 'gpu_memory_utilization')},
        'parallel': {'tensor_parallel_size': engine_config.parallel_config.tensor_parallel_size},
        'scheduler': {'max_num_seqs': engine_config.scheduler_config.max_num_seqs},
        'quantization': engine_config.model_config.quantization,
        'attention': {'selection_policy': 'vllm_automatic', 'config': attention_record,
                      'actual_backend_evidence': 'Retain worker startup log; config is not a claim of selected backend.'},
        'sampling': {key: getattr(params, key) for key in list(SAMPLING)+['stop_token_ids']},
    }
    if (engine_config.model_config.max_model_len != ENGINE['max_model_len']
            or str(engine_config.model_config.dtype) != 'torch.bfloat16'
            or engine_config.model_config.quantization is not None
            or not engine_config.model_config.enforce_eager
            or engine_config.cache_config.enable_prefix_caching
            or engine_config.parallel_config.tensor_parallel_size != 1
            or engine_config.scheduler_config.max_num_seqs != 1):
        raise ValueError('Resolved engine differs from frozen contract')
    hardware = [dict(index=i, name=torch.cuda.get_device_name(i),
                     capability=list(torch.cuda.get_device_capability(i)),
                     total_memory=torch.cuda.get_device_properties(i).total_memory)
                for i in range(torch.cuda.device_count())]
    preserve_environment(environment_path, dict(versions=versions, hardware=hardware,
                cuda_version=torch.version.cuda, requested_engine=ENGINE,
                resolved=resolved, sampler=manifest['sampler'], model_revision=REVISION,
                python=sys.version, platform=sys.platform, ready_before_study_dispatch=True))
    def generate_one(ids):
        output = llm.generate([{'prompt_token_ids': ids}], sampling_params=params, use_tqdm=False)
        if len(output) != 1:
            raise ValueError('Backend returned wrong request count')
        return output[0]
    return generate_one


def run_prepared(manifest_path, expected_manifest_sha256, local_model_path,
                 output_dir):
    """Call only after parent freeze/free-runtime authorization; no auto execution."""
    manifest, jobs = read_bundle(manifest_path, expected_manifest_sha256)
    backend = None
    def prepare():
        nonlocal backend
        backend = make_backend(manifest, local_model_path, Path(output_dir)/'environment.json')
    def generate(ids):
        return backend(ids)
    identity = dict(manifest_sha256=expected_manifest_sha256,
                    runner_sha256=sha(Path(__file__).read_bytes()),
                    model_revision=REVISION, engine=ENGINE, sampling=SAMPLING,
                    stop_token_ids=manifest['stop_token_ids'])
    return run_jobs(jobs, output_dir, identity, generate, prepare=prepare)


def main():
    """Standalone spawn-safe worker, invoked explicitly by a durable cell."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--model-path', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    run_prepared(args.manifest, args.manifest_sha256, args.model_path, args.output_dir)


if __name__ == '__main__':
    main()
