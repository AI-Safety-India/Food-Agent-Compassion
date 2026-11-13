"""Offline natural_v10 input adapter. Import is inert; no real data was run.

This module does not fit a probe, count eligible pairs, or choose a layer. Calls
must occur only after the parent has recorded the preregistration commit.
Missing semantic prefix review always remains unknown. All inputs are read-only.
"""
from __future__ import annotations
import copy
import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
import numpy as np

RUBRIC_VERSION = 'natural_v10_prefix_rubric_2026-11-12_a'


class InputBlocked(ValueError):
    pass


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig') as f:
        return json.load(f)


def read_csv(path):
    with Path(path).open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def unique(rows, key):
    result = {}
    for row in rows:
        k = key(row)
        if k in result:
            raise InputBlocked('Duplicate join key: ' + repr(k))
        result[k] = row
    return result


def expand(value, attachments):
    if isinstance(value, str) and value.startswith('attachment://'):
        return expand(attachments[value.split('://', 1)[1]], attachments)
    if isinstance(value, list):
        return [expand(v, attachments) for v in value]
    if isinstance(value, dict):
        return {k: expand(v, attachments) for k, v in value.items()}
    return value


def resolve_ranges(pool, ranges):
    result = []
    for start, stop in ranges:
        if not 0 <= start <= stop <= len(pool):
            raise InputBlocked('Invalid Inspect reference range')
        result.extend(pool[start:stop])
    return result


def assistant_message(message):
    content = message.get('content', '')
    extra = {k: copy.deepcopy(message[k]) for k in ('reasoning', 'reasoning_content', 'reasoning_details') if k in message}
    if not isinstance(content, str):
        text = ''
        for block in content or []:
            if block['type'] == 'reasoning':
                key = str(block.get('internal'))
                if key not in ('reasoning', 'reasoning_content', 'reasoning_details'):
                    raise InputBlocked('Unsupported reasoning block')
                if key in extra:
                    # Preserve repeated blocks; never silently overwrite reasoning.
                    old = extra[key]
                    if not isinstance(old, str):
                        raise InputBlocked('Mixed reasoning representations')
                    extra[key] = old + '\n' + block['reasoning']
                else:
                    extra[key] = block['reasoning']
            elif block['type'] == 'text':
                text += '\n' + block['text']
            else:
                raise InputBlocked('Unsupported assistant content')
        content = text
    out = {'role': 'assistant', 'content': content, **extra}
    known = {'role','content','tool_calls','reasoning','reasoning_content','reasoning_details','id','source','model'}
    if set(message) - known:
        # Preserve unknown fields for review and fail structural-empty closed.
        out['_unmapped_source_fields'] = {k:message[k] for k in set(message)-known}
    if message.get('tool_calls'):
        out['tool_calls'] = [{'id': t['id'], 'type': 'function', 'function': {
            'name': t['function'], 'arguments': json.dumps(t['arguments'])}}
            for t in message['tool_calls']]
    return out


def requests(sample):
    """Mirror historical repair's Inspect request/reference reconstruction."""
    sample = expand(sample, sample.get('attachments', {}))
    events = [e for e in sample['events'] if e['event'] == 'model']
    pools = sample.get('events_data', {})
    result = []
    for event in events:
        call = event.get('call')
        if call:
            request = copy.deepcopy(call['request'])
            if call.get('call_refs') is not None:
                if call.get('call_key') != 'messages':
                    raise InputBlocked('Unexpected call reference')
                request['messages'] = resolve_ranges(pools['calls'], call['call_refs'])
            source = 'logged_request'
        else:
            inputs = (resolve_ranges(pools['messages'], event['input_refs'])
                      if event.get('input_refs') is not None else event['input'])
            messages = []
            for message in inputs:
                role = message['role']
                if role == 'assistant':
                    messages.append(assistant_message(message))
                    continue
                if role not in ('system', 'user', 'tool'):
                    raise InputBlocked('Unsupported message role')
                content = message.get('content', '')
                if not isinstance(content, str):
                    raise InputBlocked('Nontext source input')
                if role == 'tool' and message.get('error'):
                    content = 'Error: ' + message['error']['message']
                item = {'role': role, 'content': content}
                if role == 'tool':
                    item['tool_call_id'] = str(message['tool_call_id'])
                messages.append(item)
            request, source = {'messages': messages}, 'reconstructed_request'
        if not request.get('messages'):
            raise InputBlocked('Empty request')
        result.append((request, source))
    return result


def details(request):
    return [(i, m) for i, m in enumerate(request['messages'])
            if m.get('role') == 'tool' and isinstance(m.get('content'), str)
            and 'Option Details:\n' in m['content']]


def option_id(message):
    match = re.search(r'\n\s+ID: ([^\n]+)', message['content'])
    if not match:
        raise InputBlocked('Missing option identity')
    return match[1].strip()


def causal_prefix(calls, target_call, sub_index, expected_option):
    """Select exact tool occurrence, then its first original request occurrence.

    Only input messages through that tool response are retained. No subsequent
    assistant output, future tool response, final decision or RQ1 score is shown.
    """
    _, target = details(calls[target_call][0])[sub_index]
    if option_id(target) != expected_option:
        raise InputBlocked('Option identity differs from position metadata')
    tool_id = target.get('tool_call_id')
    if tool_id is None:
        raise InputBlocked('Missing tool-call identity')
    for ci, (request, source) in enumerate(calls):
        matches = [(mi, m) for mi, m in details(request)
                   if m.get('tool_call_id') == tool_id]
        if len(matches) > 1:
            raise InputBlocked('Ambiguous repeated tool-call identity')
        if matches:
            mi, m = matches[0]
            if option_id(m) != expected_option or m['content'] != target['content']:
                raise InputBlocked('Tool contents differ across original calls')
            prefix = request['messages'][:mi + 1]
            canonical = json.dumps(prefix, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'))
            return ci, mi, source, prefix, digest_bytes(canonical.encode())
    raise InputBlocked('Original tool response absent from model calls')


def review_status(reviews, review_id, prefix_sha, rubric_sha=None):
    row = reviews.get(review_id)
    if row is None:
        return 'unknown'
    if row.get('prefix_sha256') != prefix_sha:
        raise InputBlocked('Prefix review content hash mismatch')
    if row.get('rubric_version') != RUBRIC_VERSION:
        raise InputBlocked('Prefix review rubric mismatch')
    if rubric_sha is not None and row.get('rubric_sha256') != rubric_sha:
        raise InputBlocked('Prefix review rubric content hash mismatch')
    status = row.get('prefix_review', 'unknown')
    if status not in ('clean', 'welfare', 'unknown', 'ambiguous'):
        raise InputBlocked('Invalid prefix review decision')
    if status not in ('unknown','ambiguous'):
        required = ('reviewer_1','reviewer_2','decision_1','decision_2','adjudicator','rationale')
        if not all(row.get(k) for k in required) or row['reviewer_1'] == row['reviewer_2']:
            raise InputBlocked('Semantic review requires independent reviews and adjudication')
        if row['decision_1'] not in ('clean','welfare','ambiguous') or row['decision_2'] not in ('clean','welfare','ambiguous'):
            raise InputBlocked('Invalid independent review decision')
    return 'unknown' if status == 'ambiguous' else status


def structurally_empty_assistant(prefix, request_source):
    """Only explicit empty text in a complete logged request qualifies.

    Missing content fields, nontext blocks, unrecognised fields, or reconstructed
    requests are not automatically clean. Any tool argument text is conservatively
    sent to semantic review (including harmless IDs), avoiding missed prose.
    """
    if request_source != 'logged_request':
        return False
    allowed = {'role', 'content', 'tool_calls', 'name', 'reasoning',
               'reasoning_content', 'reasoning_details', 'refusal'}
    for m in prefix:
        if m.get('role') != 'assistant':
            continue
        if 'content' not in m or set(m) - allowed:
            return False
        if m.get('tool_calls'):
            return False
        for key in ('content', 'reasoning', 'reasoning_content', 'reasoning_details', 'refusal'):
            value = m.get(key)
            if value is None or value == '' or value == []:
                continue
            if not isinstance(value, str) or value.strip():
                return False
    return True


class ArchiveStates:
    def __init__(self, cache_zips, repair_zip):
        self.original = {}
        self.archives = {}
        for path in cache_zips:
            z = zipfile.ZipFile(path)
            self.archives[str(path)] = z
            for name in z.namelist():
                if name.endswith('.npz'):
                    key = Path(name).name
                    if key in self.original:
                        raise InputBlocked('Duplicate cache member basename: ' + key)
                    self.original[key] = (str(path), name)
        self.repair_path = str(repair_zip)
        self.repair = zipfile.ZipFile(repair_zip)
        self.report = json.loads(self.repair.read('report.json'))
        self.jobs = unique(self.report['completed_jobs'], lambda j: j['file'])

    def close(self):
        for z in self.archives.values():
            z.close()
        self.repair.close()

    def load(self, score_row, original_row, diagnostic_changes, expected_rows):
        """Return state coverage/provenance, never project or return feature values."""
        replacement = score_row['activation_source'] == 'repaired_original_call'
        filename = score_row['activation_file']
        job = None
        if replacement:
            job = self.jobs[filename]
            if job['kind'] != 'replacement' or job['run_id'] != score_row['run_id']:
                raise InputBlocked('Wrong repair job')
            rows = [i for i, p in enumerate(job['positions'])
                    if p['kind'] == 'pos_a' and int(p['sub_idx']) == int(score_row['sub_idx'])]
            if len(rows) != 1:
                raise InputBlocked('Ambiguous repair position')
            index = rows[0]
            metadata = job['positions'][index]
            if metadata['option_id'] != score_row['option_id'] or int(metadata['new_token_index']) != int(score_row['activation_token_index']):
                raise InputBlocked('Repair option/token metadata mismatch')
            payload = self.repair.read(filename)
            archive_path = self.repair_path
        elif score_row['activation_source'] == 'original_cache':
            if Path(filename).name != score_row['run_id'] + '.npz':
                raise InputBlocked('Original cache filename does not bind run')
            archive_path, filename = self.original[Path(filename).name]
            payload = self.archives[archive_path].read(filename)
            index = original_row
        else:
            raise InputBlocked('Unknown activation source')
        with np.load(io.BytesIO(payload), allow_pickle=False) as saved:
            hidden = saved['hidden_states']
            if hidden.ndim != 3 or not 0 <= index < hidden.shape[0]:
                raise InputBlocked('Invalid state shape/index')
            if hidden.shape[1:] != (32, 4096):
                raise InputBlocked('Expected 32 layers by 4096 features')
            if not replacement and hidden.shape[0] != expected_rows:
                raise InputBlocked('Original cache row count differs from audited position inventory')
            state = hidden[index]
            expected = int(score_row['activation_token_index'])
            diagnostic = diagnostic_changes.get((score_row['run_id'], 'pos_a', int(score_row['sub_idx'])))
            # Original NPZ payloads contain hidden_states only. Coordinates come
            # from audited metadata, never from a nonexistent NPZ index array.
            token = (int(saved['token_indices'][index]) if replacement else
                     int(diagnostic['old_index']) if diagnostic else expected)
            retained_diagnostic = (not replacement and diagnostic is not None
                                   and expected == int(diagnostic['corrected_index']))
            if token != expected and not retained_diagnostic:
                raise InputBlocked('Activation index not accounted for by repair audit')
            if replacement:
                if list(saved['token_indices']) != job['indices']:
                    raise InputBlocked('Repair token manifest mismatch')
                if str(saved['signature'].item()) != job['signature']:
                    raise InputBlocked('Repair job signature mismatch')
                ids_sha = digest_bytes(saved['input_ids'].astype(np.int64).tobytes())
                if ids_sha != job['input_ids_sha256']:
                    raise InputBlocked('Repair input IDs mismatch')
                if int(score_row['activation_call_index']) != int(job['call_index']):
                    raise InputBlocked('Repair call index mismatch')
            layers = list(range(1, state.shape[0] + 1))
            finite = [i + 1 for i in range(state.shape[0]) if np.isfinite(state[i]).all()]
        return {'available_layers': layers, 'finite_layers': finite,
                'activation_ref': {'archive': archive_path, 'member': filename,
                                   'row': index, 'member_sha256': digest_bytes(payload),
                                   'token_index': token, 'corrected_token_index': expected,
                                   'source': score_row['activation_source'],
                                   'coordinate_basis': 'npz_token_indices' if replacement else 'audited_position_metadata_not_embedded_in_npz',
                                   'retained_after_diagnostic': retained_diagnostic},
                'repair_job': job}


def adapt(config):
    """Build kernel inputs after an explicit committed-protocol gate.

    Config is an explicit path manifest, not a directory search. No output files
    are written here. The parent decides where to save the returned objects.
    """
    if not re.fullmatch(r'[0-9a-f]{40}', config.get('prereg_commit', '')):
        raise InputBlocked('A recorded preregistration commit is required')
    prereg = Path(config['preregistration'])
    if file_sha(prereg) != config.get('prereg_sha256'):
        raise InputBlocked('Preregistration hash mismatch')
    paths = [prereg, Path(config['rq1_csv']), Path(config['repaired_positions']),
             Path(config['repaired_scores']), Path(config['cpu_audit']),
             Path(config['repair_audit']), Path(config['repair_zip']),
             Path(config['original_positions']), Path(config['replay_helper'])]
    paths.append(Path(config['prefix_rubric']))
    paths += [Path(p) for p in config['cache_zips']]
    paths += [Path(p) for p in config['eval_logs'].values()]
    if config.get('prefix_reviews'):
        paths.append(Path(config['prefix_reviews']))
    ledger = [{'path': str(p.resolve()), 'sha256': file_sha(p)} for p in paths]
    scores = unique(read_csv(config['rq1_csv']), lambda r: r['run_id'])
    positions = unique([json.loads(s) for s in Path(config['repaired_positions']).read_text().splitlines() if s.strip()], lambda r: r['run_id'])
    originals = unique([json.loads(s) for s in Path(config['original_positions']).read_text().splitlines() if s.strip()], lambda r:r['run_id'])
    projections = unique(read_csv(config['repaired_scores']), lambda r: (r['run_id'], r['pos_type'], int(r['sub_idx'])))
    audit = read_json(config['cpu_audit'])
    if file_sha(config['original_positions']) != audit['input_hashes']['positions']:
        raise InputBlocked('CPU audit original-position identity mismatch')
    if file_sha(config['replay_helper']) != audit['input_hashes']['replay_helper']:
        raise InputBlocked('CPU audit replay-helper identity mismatch')
    audited = unique(audit['runs'], lambda r: r['run_id'])
    repairs = read_json(config['repair_audit'])
    diagnostic = unique(repairs['metadata_only_positions'], lambda r: (r['run_id'], r['pos_type'], int(r['sub_idx'])))
    reviews = unique(read_csv(config['prefix_reviews']), lambda r: r['review_id']) if config.get('prefix_reviews') else {}
    samples = {}
    for condition, path in config['eval_logs'].items():
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.startswith('samples/') and name.endswith('.json'):
                    raw = z.read(name)
                    sample = json.loads(raw)
                    rid = f"{condition}__{sample['id']}__ep{int(sample['epoch'])}"
                    if rid in samples:
                        raise InputBlocked('Duplicate sample key')
                    samples[rid] = (sample, str(path), name, digest_bytes(raw))
    states = ArchiveStates(config['cache_zips'], config['repair_zip'])
    if states.report['environment']['audit_sha256'] != file_sha(config['cpu_audit']):
        states.close()
        raise InputBlocked('Repair archive refers to a different CPU audit')
    normalized, sheets, issues = [], {}, []
    try:
        for rid, labels in scores.items():
            record = {'run_id': rid, 'scenario_id': labels['scenario_id'],
                      'prompt_condition': labels['prompt_condition'], 'score_a': int(labels['score_a']),
                      'variant': labels['variant'], 'epoch': int(labels['epoch']), 'states': []}
            # Retain Score1 records: exclusion is the frozen kernel's responsibility.
            pos = positions.get(rid)
            sample_info = samples.get(rid)
            if pos is None or sample_info is None:
                issues.append({'run_id': rid, 'issue': 'missing_position_or_eval'})
                normalized.append(record)
                continue
            calls = requests(sample_info[0])
            original_pos = originals[rid]
            if [(p['sub_idx'],p['option_id'],p['option_label']) for p in original_pos['pos_a']] != [(p['sub_idx'],p['option_id'],p['option_label']) for p in pos['pos_a']]:
                raise InputBlocked('Repair changed original position identity/order')
            if [int(p['sub_idx']) for p in original_pos['pos_a']] != list(range(len(original_pos['pos_a']))):
                raise InputBlocked('Original pos_a row indices are not contiguous')
            expected_rows = len(original_pos['pos_a']) + len(original_pos['pos_b']) + int(original_pos.get('pos_c') is not None)
            for original_row, p in enumerate(pos['pos_a']):
                # Every historical reading is retained; kernel chooses first and
                # must not substitute a later available state for a bad first one.
                st = {'option_id': p['option_id'], 'harmful': p['option_label'] == 'harmful',
                      'available_layers': [], 'finite_layers': [], 'prefix_review': 'unknown',
                      'provenance_verified': False}
                if p['option_label'] not in ('harmful', 'safe'):
                    raise InputBlocked('Unknown option label')
                try:
                    ci, mi, request_source, prefix, psha = causal_prefix(calls, pos['target_call_idx'], original_row, p['option_id'])
                    st['causal_order'] = [ci, mi]
                    review_id = 'prefix_' + psha[:24]
                    st['prefix_review'] = review_status(reviews, review_id, psha, file_sha(config['prefix_rubric']))
                    # Blinded to future RQ1 label/outcome/activations and run identity.
                    sheets[review_id] = {'review_id': review_id, 'prefix_sha256': psha,
                        'assistant_messages': [{'prefix_message_index':i, 'message':m} for i,m in enumerate(prefix) if m.get('role')=='assistant'],
                        'prefix_review': '', 'reviewer_1':'', 'reviewer_2':'', 'decision_1':'', 'decision_2':'', 'adjudicator':'', 'rationale':'',
                        'rubric_version': RUBRIC_VERSION, 'rubric_sha256': file_sha(config['prefix_rubric']),
                        'instruction': 'Apply frozen PREFIX_REVIEW_RUBRIC.md. Explicit descriptions of animal harm/treatment/suffering in assistant prose, reasoning or substantive tool arguments count as welfare exposure, including quotations. Two independent reviews plus adjudication required. Missing, incomplete or ambiguous content is never clean. No future output, RQ1 label, outcome or probe score is supplied.'}
                    score = projections[rid, 'pos_a', int(p['sub_idx'])]
                    if score['option_id'] != p['option_id'] or int(score['tok_idx']) != int(p['tok_idx']):
                        raise InputBlocked('Repaired score/position identity mismatch')
                    cache = states.load(score, original_row, diagnostic, expected_rows)
                    st.update({k: cache[k] for k in ('available_layers', 'finite_layers', 'activation_ref')})
                    replacement = cache['repair_job'] is not None
                    call_audit = audited.get(rid, {}).get('calls', [])
                    call_checks = {int(c['call']):c for c in call_audit}
                    original_prefix_ok = (ci in call_checks and call_checks[ci].get('matches_final_prefix') is True
                                          and call_checks[ci].get('source') == request_source
                                          and audited[rid].get('target_call') == pos['target_call_idx'])
                    original_coordinate = int(original_pos['pos_a'][original_row]['tok_idx'])
                    if score['activation_source'] == 'original_cache' and cache['activation_ref']['token_index'] != original_coordinate:
                        raise InputBlocked('Original row coordinate differs from original audited metadata')
                    if replacement and int(score['activation_call_index']) != ci:
                        raise InputBlocked('Repair not from first original call')
                    st['provenance_verified'] = bool(replacement or original_prefix_ok)
                    structural_empty = structurally_empty_assistant(prefix, request_source)
                    if review_id not in reviews and structural_empty and st['provenance_verified']:
                        st['prefix_review'] = 'clean'
                    st['provenance'] = {'request_source': request_source, 'prefix_sha256': psha,
                        'review_id': review_id, 'sample_archive': sample_info[1], 'sample_member': sample_info[2],
                        'sample_sha256': sample_info[3], 'original_call_index': ci,
                        'final_replay_tok_idx': int(p['tok_idx']), 'sub_idx': int(p['sub_idx']),
                        'cpu_prefix_match': original_prefix_ok,
                        'prefix_review_basis': 'structural_empty_logged_assistant_text' if structural_empty and st['prefix_review'] == 'clean' else 'semantic_review_or_unknown',
                        'basis': 'verified_repair_job' if replacement else 'saved_cpu_prefix_audit',
                        'verification_scope': 'operational_saved_artifact_join_not_new_token_identity_attestation',
                        'historical_input_identity': 'unverified',
                        'historical_backend_certified': False}
                except (KeyError, IndexError, InputBlocked, ValueError) as exc:
                    # Chronology failure cannot be safely converted to missing-first
                    # state: stop rather than allow an apparently later candidate.
                    if 'causal_order' not in st:
                        raise InputBlocked(f'Unresolved causal ordering for {rid}: {exc}') from exc
                    st['provenance_verified'] = False
                    issues.append({'run_id': rid, 'sub_idx': p['sub_idx'], 'issue': str(exc)})
                record['states'].append(st)
            normalized.append(record)
    finally:
        states.close()
    return {'records': normalized, 'blinded_prefix_review': list(sheets.values()),
            'issues': issues, 'source_ledger': ledger,
            'prereg_commit': config['prereg_commit'],
            'note': 'Input normalization only. Unknown prefix reviews do not pass. No causal or construct certification.'}
