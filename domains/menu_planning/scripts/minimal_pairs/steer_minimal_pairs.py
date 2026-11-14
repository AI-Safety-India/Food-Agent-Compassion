"""Reduced, preregistered Stage 3. No generation, patching or paid-resource setup."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback
import numpy as np
import extract_minimal_pairs as ex

SEED = 20261114
ALPHAS = [-8, -4, -2, 0, 2, 4, 8]
FREEZE_SHA = '780e326a329d04531b186b2825f5f3e6dd695fe1f3dc68be207df983cc28ead7'
PREREG_COMMIT = '61577bd'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def prepare(root):
    """Local only; freeze exact vectors, inputs and jobs before inference."""
    frozen = root / 'stage1/frozen'
    assert ex.sha(frozen / 'FROZEN.json') == FREEZE_SHA
    assert read(frozen / 'FROZEN.json')['layer'] == 21
    assert ex.sha(frozen / 'primary.npz') == 'd84f40f0888b868a34bcde064d5692516d99ecfbb7591a78edae006dbc49fab7'
    extraction = root / 'extraction'
    verified={x['target']:x['sha256'] for x in read(root/'TRANSFER_MANIFEST.json')}
    for name in ['index.jsonl','layer_21.npz','environment.json','calibration.json']:
        assert ex.sha(extraction/name)==verified['extraction/'+name]
    rows = [json.loads(s) for s in (extraction / 'index.jsonl').read_text().splitlines()]
    with np.load(frozen / 'primary.npz', allow_pickle=False) as z:
        d = z['direction'].copy()
    assert d.shape == (4096,) and np.isclose(np.linalg.norm(d), 1)
    with np.load(extraction / 'layer_21.npz', allow_pickle=False) as z:
        assert int(z['layer']) == 21
        assert z['positions'].tolist() == ['endA','endB','meanA','meanB','final']
        a = z['activations'][:, :2].astype(np.float32)
    assert a.shape == (1002, 2, 4096)
    train = [i for i,r in enumerate(rows) if r['condition']=='none' and r['set']=='welfare_train']
    neutral = [i for i,r in enumerate(rows) if r['condition']=='none' and r['set']=='neutral_control']
    assert len(train)==140 and len(neutral)==94
    sigma = float(np.std(a[train] @ d, ddof=0))
    assert np.isfinite(sigma) and sigma > 0
    line1, line2 = [], []
    for i in neutral:
        assert rows[i]['A_is'] in ('line_1','line_2')
        j = 0 if rows[i]['A_is']=='line_1' else 1
        line1.append(a[i,j]); line2.append(a[i,1-j])
    nd = np.mean(line1, axis=0)-np.mean(line2, axis=0)
    assert np.isfinite(nd).all() and np.linalg.norm(nd)>0
    nd /= np.linalg.norm(nd)
    rng = np.random.default_rng(SEED)
    random = rng.normal(size=(10,4096))
    random /= np.linalg.norm(random,axis=1,keepdims=True)
    directions = np.vstack([d,nd,random]).astype(np.float32)
    selected = sorted([r for r in rows if r['condition']=='none'],key=lambda r:r['prompt_id'])
    held = [r for r in selected if r['set']=='welfare_heldout']
    neu = [r for r in selected if r['set']=='neutral_control']
    assert len(held)==100 and len(neu)==94 and len(selected)==334
    sanity = held[:2]+neu[:2]
    assert sanity[0]['pair_id']==sanity[1]['pair_id'] and sanity[2]['pair_id']==sanity[3]['pair_id']
    jobs=[]
    for r in selected:
        groups=[(0,[v for v in ALPHAS if v])]
        if r['set']=='welfare_heldout':
            groups += [(1,[v for v in ALPHAS if v])]+[(j,[-4,4]) for j in range(2,12)]
        for direction,doses in groups:
            for target in ['A','B']:
                for alpha in doses:
                    jobs.append(dict(prompt_id=r['prompt_id'],direction=direction,target=target,alpha=alpha))
    assert len(jobs)==9208
    out=root/'stage3/plan'
    out.mkdir(parents=True,exist_ok=False)
    with (out/'directions.npz').open('xb') as f:
        np.savez(f,directions=directions)
    ex.write_json(out/'inputs.json',selected)
    ex.write_json(out/'jobs.json',jobs)
    ex.write_json(out/'PLAN.json',dict(prereg_commit=PREREG_COMMIT,prereg_sha256=ex.sha(root/'STEERING_PREREG.md'),
        freeze_sha256=FREEZE_SHA,layer=21,sigma=sigma,seed=SEED,study_forwards=9208,engineering_forwards=8,
        source_hashes={n:ex.sha(extraction/n) for n in ['index.jsonl','layer_21.npz','environment.json','calibration.json']},
        source_primary_sha256=ex.sha(frozen/'primary.npz'),extractor_sha256=ex.sha(ex.__file__),
        worker_sha256=ex.sha(__file__),files={n:ex.sha(out/n) for n in ['directions.npz','inputs.json','jobs.json']},
        sanity=[dict(prompt_id=r['prompt_id'],target=['A','B','A','B'][i]) for i,r in enumerate(sanity)],
        review='Sub-agent code review skipped at explicit user request; four-prompt check required',
        alpha_zero='Reuse original cached logits only after exact sanity equivalence',paid_authorized=False))
    print('PLAN_READY',len(jobs),sigma,flush=True)


def worker(root, free):
    if not free:
        raise RuntimeError('Explicit free-runtime confirmation required')
    planroot=root/'stage3/plan'; plan=read(planroot/'PLAN.json')
    if ex.sha(__file__)!=plan['worker_sha256'] or ex.sha(ex.__file__)!=plan['extractor_sha256']:
        raise RuntimeError('Code hash differs from frozen execution plan')
    for name,digest in plan['files'].items():
        assert ex.sha(planroot/name)==digest
    for name,digest in plan['source_hashes'].items():
        assert ex.sha(root/'extraction'/name)==digest
    assert ex.sha(root/'STEERING_PREREG.md')==plan['prereg_sha256']
    rows=read(planroot/'inputs.json'); lookup={r['prompt_id']:r for r in rows}
    jobs=read(planroot/'jobs.json')
    with np.load(planroot/'directions.npz',allow_pickle=False) as z: directions=z['directions']
    assert directions.shape==(12,4096) and np.isfinite(directions).all()
    run=root/'stage3/run'
    run.mkdir(exist_ok=False)
    with ex.lock(run):
        manifest=root/'preparation/snapshot_manifest.json'
        args=argparse.Namespace(snapshot=read(manifest)['snapshot'],snapshot_manifest=str(manifest),
            helper=str(Path(__file__).with_name('audited_helper.py')))
        model,tok,helper,env=ex.load_runtime(args)
        old=read(root/'extraction/environment.json')
        for key in ['model_class','model_module_source_sha256','helper_sha256','attention_implementation','torch','transformers','numpy']:
            assert env[key]==old[key],key
        ex.write_json(run/'environment.json',env)
        _,pairs=ex.load_data(root/'inputs/prompts.jsonl',root/'inputs/pairs.json')
        for r in rows:
            fresh=ex.prepare(r,pairs[r['pair_id']],tok,whitespace_boundary=True)
            for key in ['rendered','input_ids','spans','positions']:
                assert fresh[key]==r[key],(r['prompt_id'],key)
        module=dict(model.named_modules())['model.layers.20']
        import torch
        device=next(model.parameters()).device
        vectors=torch.tensor(directions,device=device,dtype=torch.float32)
        raw=run/'raw.jsonl'
        def forward(job, phase, number):
            r=lookup[job['prompt_id']]; indices=r['spans'][job['target']+'_line']['token_indices']
            evidence=[]
            delta=(vectors[job['direction']]*float(job['alpha']*plan['sigma'])).to(torch.bfloat16)
            def hook(mod, inputs, output):
                assert isinstance(output,torch.Tensor) and tuple(output.shape)==(1,len(r['input_ids']),4096)
                changed=output.clone()
                changed[:,indices,:] += delta.to(output.device)
                if phase=='sanity':
                    actual=torch.any(changed!=output,dim=-1)[0].nonzero().flatten().tolist()
                    assert actual==(indices if job['alpha'] else []),(actual,indices)
                    evidence.append(actual)
                else:
                    evidence.append(True)
                return changed
            ex.append_event(run,phase=phase,number=number,state='intent',job=job)
            handle=module.register_forward_hook(hook)
            try:
                # Same forward flags and full-token logit computation as the audited extractor.
                with torch.no_grad():
                    output=model(input_ids=torch.tensor([r['input_ids']],device=device,dtype=torch.long),
                                 output_hidden_states=True,use_cache=False)
                logits=output.logits[0,r['positions']['final']].detach().float().cpu().numpy()
            finally:
                handle.remove()
            assert len(evidence)==1 and np.isfinite(logits).all()
            ids=r['answer_token_ids']; values=[float(logits[ids[k]]) for k in ['A','B']]
            result=dict(**job,phase=phase,number=number,pair_id=r['pair_id'],set=r['set'],mirrored=r['mirrored'],
                target_is=r[job['target']+'_is'],candidate_logits=values,
                baseline_logits=[r['candidate_logits'][str(ids[k])] for k in ['A','B']],
                greedy_first_id=int(logits.argmax()),token_indices=indices,input_sha256=ex.digest(r['input_ids']),
                hook_calls=len(evidence),changed_positions=evidence[0] if phase=='sanity' else None)
            with raw.open('a',encoding='utf-8') as f:
                f.write(json.dumps(result,allow_nan=False)+'\n'); f.flush(); os.fsync(f.fileno())
            ex.append_event(run,phase=phase,number=number,state='complete',result_sha256=ex.digest(result))
            return result
        checks=[]
        for i,s in enumerate(plan['sanity']):
            for alpha in [0,4]:
                checks.append(forward(dict(**s,direction=0,alpha=alpha),'sanity',2*i+int(alpha!=0)))
        zeros=[r for r in checks if r['alpha']==0]
        baseline=np.array([r['baseline_logits'] for r in zeros]).flatten()
        actual=np.array([r['candidate_logits'] for r in zeros]).flatten()
        correlation=float(np.corrcoef(baseline,actual)[0,1])
        exact=bool(np.array_equal(baseline,actual))
        ex.write_json(run/'SANITY.json',dict(exact=exact,correlation=correlation,checks=8,
            hook_isolation=True,passed=exact and correlation>.999))
        if not exact or not correlation>.999:
            raise RuntimeError('Sanity failure; no study forwards permitted')
        print('SANITY_PASS: exact baseline logits; correlation',correlation,flush=True)
        for i,job in enumerate(jobs):
            forward(job,'study',i)
            if (i+1)%100==0 or i+1==len(jobs):
                ex.write_json(run/'progress.json',dict(completed=i+1,total=len(jobs)),exclusive=False)
                print('PROGRESS',i+1,'/',len(jobs),flush=True)
        ex.write_json(run/'COMPLETE.json',dict(study_forwards=len(jobs),engineering_forwards=8,
            plan_sha256=ex.sha(planroot/'PLAN.json'),files={n:ex.sha(run/n) for n in ['raw.jsonl','ledger.jsonl','SANITY.json','environment.json']}))


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','worker'])
    p.add_argument('--root',required=True);p.add_argument('--free-runtime-confirmed',action='store_true')
    args=p.parse_args();root=Path(args.root)
    if args.mode=='prepare':
        prepare(root)
    else:
        try:
            worker(root,args.free_runtime_confirmed)
        except BaseException:
            dest=root/'stage3/WORKER_FAILED.json'
            if not dest.exists(): ex.write_json(dest,dict(traceback=traceback.format_exc()))
            raise


if __name__=='__main__':main()
