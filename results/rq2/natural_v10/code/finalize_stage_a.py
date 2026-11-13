"""Freeze blinded reviews, then separately evaluate only committed frozen inputs.

Import is inert. Freeze hashes outcome-bearing inputs without parsing them.
Evaluate uses existing normalized states only; no cache reads, models or fitting.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from input_adapter import InputBlocked, RUBRIC_VERSION, file_sha, read_csv, review_status, unique
from feasibility_kernel import build_pairs
from run_stage_a import committed_bytes

DECISIONS = {'clean', 'welfare', 'ambiguous'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_lines(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]


def assistant_text_sha(messages):
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def combine(groups, first, second, adjudications, rubric_sha, expected_groups=731,
            expected_members=1398):
    """Pure blinded join; no outcome fields are accepted or consulted."""
    gs = unique(groups, lambda x: x['group_id'])
    a = unique(first, lambda x: x['group_id'])
    b = unique(second, lambda x: x['group_id'])
    adj = unique(adjudications, lambda x: x['group_id'])
    wanted = {f'G{i:04d}' for i in range(expected_groups)}
    if set(gs) != wanted or set(a) != wanted or set(b) != wanted:
        raise InputBlocked('Missing or unexpected group/reviewer coverage')
    rows, disagreements = [], set()
    for gid in sorted(gs):
        g, one, two = gs[gid], a[gid], b[gid]
        if not g.get('members') or not re.fullmatch('[0-9a-f]{64}', g.get('assistant_text_sha256', '')):
            raise InputBlocked('Missing members or malformed assistant text identity')
        if not isinstance(g.get('assistant_messages'), list) or assistant_text_sha(g['assistant_messages']) != g['assistant_text_sha256']:
            raise InputBlocked('Assistant message content hash mismatch')
        if g['rubric_sha256'] != rubric_sha or g['rubric_version'] != RUBRIC_VERSION:
            raise InputBlocked('Group rubric mismatch')
        for r in (one, two):
            if r['assistant_text_sha256'] != g['assistant_text_sha256']:
                raise InputBlocked('Assistant text hash mismatch')
            if r.get('decision') not in DECISIONS or not r.get('reviewer') or not r.get('rationale'):
                raise InputBlocked('Invalid reviewer decision/provenance')
        if one['reviewer'] == two['reviewer']:
            raise InputBlocked('Reviewers must be independent identities')
        final = one['decision']
        adjudicator = 'independent_agreement'
        rationale = one['rationale'] + ' | ' + two['rationale']
        if one['decision'] != two['decision']:
            disagreements.add(gid)
            if gid not in adj:
                raise InputBlocked('Missing disagreement adjudication: ' + gid)
            resolution = adj[gid]
            if resolution.get('assistant_text_sha256') != g['assistant_text_sha256']:
                raise InputBlocked('Adjudication text hash mismatch')
            final = resolution.get('decision', resolution.get('final_decision'))
            adjudicator = resolution.get('adjudicator', resolution.get('reviewer'))
            rationale = resolution.get('rationale')
            if final not in DECISIONS or adjudicator != 'root_blinded_prefix_adjudication' or not rationale:
                raise InputBlocked('Invalid root adjudication')
        for member in g['members']:
            sha = member['prefix_sha256']
            if not re.fullmatch('[0-9a-f]{64}', sha) or member['review_id'] != 'prefix_' + sha[:24]:
                raise InputBlocked('Invalid member prefix identity')
            rows.append(dict(member, group_id=gid, assistant_text_sha256=g['assistant_text_sha256'],
                prefix_review='unknown' if final == 'ambiguous' else final,
                reviewer_1=one['reviewer'], reviewer_2=two['reviewer'],
                decision_1=one['decision'], decision_2=two['decision'],
                adjudicator=adjudicator, rationale=rationale,
                rubric_version=RUBRIC_VERSION, rubric_sha256=rubric_sha))
    if set(adj) != disagreements:
        raise InputBlocked('Adjudications must cover exactly disagreements')
    if len(rows) != expected_members:
        raise InputBlocked('Unexpected full-prefix member count')
    unique(rows, lambda x: x['review_id'])
    return rows


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def freeze(stage, output, rq1, tuning, rubric):
    if output.exists():
        raise InputBlocked('Output directory already exists')
    packet_files = sorted((stage / 'review_packets').glob('batch_*.json'))
    groups_path = stage / 'review_packets/groups.json'
    reviews = [stage / f'reviewer_{s}.jsonl' for s in ('a', 'b', 'c')]
    adjudication = stage / 'adjudications.jsonl'
    code = Path(__file__).resolve().parent
    sources = packet_files + [groups_path] + reviews + [adjudication, stage / 'normalized_records.json',
        rq1, tuning, rubric] + [code / n for n in
        ('finalize_stage_a.py', 'feasibility_kernel.py', 'input_adapter.py', 'run_stage_a.py')]
    ledger = [{'path': str(p.resolve()), 'sha256': file_sha(p)} for p in sources]
    groups = [g for p in packet_files for g in read_json(p)]
    if read_json(groups_path) != groups:
        raise InputBlocked('Review groups differ from batch packets')
    aa, bb, cc = map(read_lines, reviews)
    if {x['group_id'] for x in aa} != {f'G{i:04d}' for i in range(500)} or {x['group_id'] for x in cc} != {f'G{i:04d}' for i in range(500, 731)}:
        raise InputBlocked('A/C assigned coverage mismatch')
    rows = combine(groups, aa + cc, bb, read_lines(adjudication), file_sha(rubric))
    # Recheck sources before publishing; none of the outcome-bearing files parsed.
    if any(file_sha(x['path']) != x['sha256'] for x in ledger):
        raise InputBlocked('Source changed during freeze')
    output.mkdir(parents=False, exist_ok=False)
    csv_path = output / 'prefix_reviews.csv'
    with csv_path.open('x', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    manifest = dict(version=1, sources=ledger, prefix_reviews_sha256=file_sha(csv_path),
        normalized_records=str((stage / 'normalized_records.json').resolve()),
        rq1_csv=str(rq1.resolve()), tuning=str(tuning.resolve()), rubric=str(rubric.resolve()),
        code_paths=[str((code / n).resolve()) for n in
        ('finalize_stage_a.py', 'feasibility_kernel.py', 'input_adapter.py', 'run_stage_a.py')])
    write_json(output / 'source_hashes.json', manifest)
    write_json(output / 'review_summary.json', dict(groups=len(groups), prefixes=len(rows),
        final_decisions=dict(Counter(r['prefix_review'] for r in rows)),
        outcome_data_parsed=False, delegated_review=True))


def verify_committed(repo, frozen, commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise InputBlocked('Actual full freeze commit required')
    manifest_path = frozen / 'source_hashes.json'
    for path in (manifest_path, frozen / 'prefix_reviews.csv', frozen / 'review_summary.json'):
        if path.read_bytes() != committed_bytes(repo, commit, path):
            raise InputBlocked('Frozen artifact differs from commit: ' + str(path))
    manifest = read_json(manifest_path)
    if file_sha(frozen / 'prefix_reviews.csv') != manifest['prefix_reviews_sha256']:
        raise InputBlocked('Frozen CSV hash mismatch')
    required_code = {str(Path(__file__).resolve().parent / n) for n in
        ('finalize_stage_a.py', 'feasibility_kernel.py', 'input_adapter.py', 'run_stage_a.py')}
    if set(manifest['code_paths']) != required_code:
        raise InputBlocked('Frozen implementation paths mismatch')
    sources = unique(manifest['sources'], lambda x: x['path'])
    for path in required_code | {manifest[k] for k in ('normalized_records', 'rq1_csv', 'tuning', 'rubric')}:
        if path not in sources:
            raise InputBlocked('Missing required source hash')
    for row in sources.values():
        if file_sha(row['path']) != row['sha256']:
            raise InputBlocked('Current source hash mismatch: ' + row['path'])
    for path in required_code:
        if Path(path).read_bytes() != committed_bytes(repo, commit, Path(path)):
            raise InputBlocked('Code differs from freeze commit')
    return manifest


def evaluate(repo, frozen, output, commit, outcome_column):
    if output.exists():
        raise InputBlocked('Output directory already exists')
    if outcome_column != 'outcome':
        raise InputBlocked('Frozen original outcome column must be outcome')
    manifest = verify_committed(repo, frozen, commit)
    # All source hashes verified before any labels/outcomes are parsed.
    records = read_json(manifest['normalized_records'])
    reviews = unique(read_csv(frozen / 'prefix_reviews.csv'), lambda x: x['review_id'])
    rubric_sha = file_sha(manifest['rubric'])
    for r in records:
        for state in r['states']:
            prov = state.get('provenance', {})
            rid = prov.get('review_id')
            if rid in reviews:
                state['prefix_review'] = review_status(reviews, rid, prov['prefix_sha256'], rubric_sha)
            elif prov.get('prefix_review_basis') != 'structural_empty_logged_assistant_text':
                state['prefix_review'] = 'unknown'
    tuning = read_json(manifest['tuning'])
    dev = {r['scenario_id'] for r in tuning}
    all_scenarios = {r['scenario_id'] for r in records}
    if len(tuning) != 10 or len(dev) != 10 or len(all_scenarios - dev) != 40 or not dev <= all_scenarios:
        raise InputBlocked('Expected frozen 10/40 scenario split')
    result = build_pairs(records, dev, all_scenarios - dev, list(range(1, 33)),
                         ['base', 'price_swap', 'rating_swap', 'reversed'])
    original = unique(read_csv(manifest['rq1_csv']), lambda x: x['run_id'])
    if set(original) != {r['run_id'] for r in records}:
        raise InputBlocked('Original CSV run coverage differs')
    for r in records:
        old = original[r['run_id']]
        if any(str(r[k]) != old[k] for k in ('scenario_id', 'prompt_condition', 'score_a', 'variant', 'epoch')) or outcome_column not in old:
            raise InputBlocked('Original CSV exact run join mismatch')
    counts = Counter()
    all_counts = Counter(('development' if r['scenario_id'] in dev else 'evaluation',
                          r['prompt_condition'], r['score_a'], original[r['run_id']][outcome_column])
                         for r in records)
    for pair in result['pairs']:
        for label in ('positive', 'negative'):
            row = pair[label]
            counts[(pair['split'], pair['prompt_condition'], label, original[row['run_id']][outcome_column])] += 1
    output.mkdir(parents=False, exist_ok=False)
    write_json(output / 'pair_manifest.json', result['pairs'])
    write_json(output / 'exclusions.json', result['exclusions'])
    summary = {k: v for k, v in result.items() if k not in ('pairs', 'exclusions')}
    summary.update(freeze_commit=commit, source_hashes=manifest['sources'],
        source_manifest_sha256=file_sha(frozen / 'source_hashes.json'),
        prefix_reviews_sha256=manifest['prefix_reviews_sha256'], outcome_column=outcome_column,
        all_run_outcomes=[dict(split=k[0], prompt=k[1], score_a=k[2], outcome=k[3], count=v) for k,v in sorted(all_counts.items())],
        paired_run_outcomes=[dict(split=k[0], prompt=k[1], label=k[2], outcome=k[3], count=v) for k,v in sorted(counts.items())])
    write_json(output / 'summary.json', summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    f = sub.add_parser('freeze')
    for name in ('stage', 'output', 'rq1', 'tuning', 'rubric'):
        f.add_argument('--' + name, type=Path, required=True)
    e = sub.add_parser('evaluate')
    for name in ('repo', 'frozen', 'output'):
        e.add_argument('--' + name, type=Path, required=True)
    e.add_argument('--commit', required=True)
    e.add_argument('--outcome-column', choices=['outcome'], default='outcome')
    args = vars(parser.parse_args()); action = args.pop('action')
    (freeze if action == 'freeze' else evaluate)(**args)


if __name__ == '__main__':
    main()
