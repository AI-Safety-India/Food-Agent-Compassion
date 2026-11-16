"""Frozen Stage1 evaluation CLI. Never execute before root commits training freeze."""
import argparse
import json
from pathlib import Path
import numpy as np
import evaluate_stage1 as e
import train_stage1 as train
import analyze_stage0 as stage0


def run(args):
    if not args.evaluation_authorized: raise ValueError('Explicit post-freeze evaluation authorization required')
    out=Path(args.output)
    if out.exists(): raise ValueError('Immutable output already exists')
    repo=Path(__file__).resolve().parents[4]
    frozen=e.verify_evaluation_freeze(args.freeze,args.freeze_sha,args.training_commit,args.freeze_commit,args.eval_commit,repo)
    train.verify_code_commit(args.eval_commit,[__file__,e.__file__,train.__file__,stage0.__file__],repo)
    root=Path(args.extraction); completion=root/'COMPLETE.json'
    if train.sha(completion)!=frozen['source_extraction_complete_sha256']: raise ValueError('Extraction completion differs from training freeze')
    if train.sha(args.transfer_manifest)!=args.transfer_manifest_sha: raise ValueError('Transfer manifest digest differs')
    transfer=json.loads(Path(args.transfer_manifest).read_text())
    if not isinstance(transfer,list): raise ValueError('Expected DOWNLOAD/TRANSFER manifest list')
    entries={r['target']:r for r in transfer}
    if len(entries)!=len(transfer): raise ValueError('Duplicate transfer entry')
    done=json.loads(completion.read_text())
    def verify_transfer(path):
        key='extraction/'+Path(path).name
        item=entries[key]
        if Path(path).stat().st_size!=item['bytes'] or train.sha(path)!=item['sha256']: raise ValueError('Transfer identity mismatch: '+key)
        if Path(path).name!='COMPLETE.json' and done['files'][Path(path).name]!=item['sha256']: raise ValueError('Completion/transfer mismatch')
        return item['sha256']
    for p in [completion,root/'index.jsonl',root/'calibration.json']: verify_transfer(p)
    rows,calibration=stage0.read_verified(root/'index.jsonl',root/'calibration.json',completion)
    canonical=stage0.read_frozen_prompts(frozen['sources']['prompts']['path'])
    stage0.observations(rows,calibration,canonical_records=canonical)
    saved_stage0=json.loads(Path(frozen['sources']['stage0']['path']).read_text())
    if saved_stage0['gate']['stop']: raise ValueError('Stage0 failed')
    if saved_stage0['flagged_mechanisms_for_secondary_only']: raise ValueError('Unexpected flagged mechanisms; frozen no-exclusions protocol cannot silently omit')
    ix={s:[i for i,r in enumerate(rows) if r['set']==s and r['condition']=='none'] for s in ('welfare_train','welfare_heldout','neutral_control')}
    tr,ho,ne=( [rows[i] for i in ix[s]] for s in ('welfare_train','welfare_heldout','neutral_control'))
    if len(tr)!=140 or [r['prompt_id'] for r in tr]!=frozen['train_prompt_ids']: raise ValueError('Training identities differ')
    e.validate_evaluation_rows(ho,ne)
    intent=out.with_name(out.name+'.intent.json')
    train.write_new(intent,{'freeze_sha256':args.freeze_sha,'evaluation_commit':args.eval_commit,
                           'output':str(out),'policy':'No automatic rerun after this intent; preserve failure evidence'})
    # All provenance and committed freeze guards above precede first np.load.
    helper=train.audited_module(frozen['sources']['helper']['path'])
    artifacts={}
    for name in ('primary','secondary','length_adjusted','length_adjusted_secondary'):
        with np.load(Path(args.freeze)/(name+'.npz'),allow_pickle=False) as z: artifacts[name]={k:z[k] for k in z.files}
    bow=json.loads((Path(args.freeze)/'bow.json').read_text())
    layers={}
    layer_sources={}
    for layer in sorted({frozen['layer'],frozen['secondary']['layer']}):
        p=root/f'layer_{layer:02d}.npz'; digest=verify_transfer(p)
        layers[layer]=e.load_frozen_layer(p,digest,layer); layer_sources[p.name]=digest
    results={}
    for method,layer,artifact_name in [('primary',frozen['layer'],'primary'),('secondary',frozen['secondary']['layer'],'secondary')]:
        array=layers[layer]; fit=artifacts[artifact_name]
        hx=array[ix['welfare_heldout']]; nx=array[ix['neutral_control']]
        result=e.evaluate_method(hx,ho,nx,ne,fit['direction'],float(fit.get('intercept',0)),helper)
        result['length_descriptive']=e.length_descriptives(hx[:,:2]@fit['direction'],ho)
        result['length_adjusted']=e.evaluate_length_adjusted(hx,ho,artifacts['length_adjusted' if method=='primary' else 'length_adjusted_secondary'])
        result['layer']=layer; result['determines_gate']=method=='primary'
        results[method]=result
    p=layers[frozen['layer']]
    baselines=e.evaluate_baselines(p[ix['welfare_train'],:2],tr,p[ix['welfare_heldout'],:2],ho,artifacts['primary']['direction'],helper,bow)
    result={'specification':e.SPECIFICATION,'primary':results['primary'],'secondary_logistic':results['secondary'],'baselines':baselines,
      'gate':e.primary_gate(results['primary'],baselines),'mechanism_exclusion_sensitivity':'Identical to primary: Stage0 flagged zero mechanisms; no exclusions',
      'coverage':{'train_prompts':140,'heldout_prompts':100,'neutral_prompts':94,'heldout_mechanisms':10},
      'provenance':{'freeze_sha256':args.freeze_sha,'freeze_commit':args.freeze_commit,'training_commit':args.training_commit,'evaluation_commit':args.eval_commit,
       'completion_sha256':train.sha(completion),'transfer_manifest_sha256':args.transfer_manifest_sha,'layer_files':layer_sources,
       'code_sha256':train.sha(__file__),'evaluator_sha256':train.sha(e.__file__),'index_sha256':train.sha(root/'index.jsonl')},
      'limitations':['Stage1 observational statistics do not alone authorize a new model run','Secondary logistic does not change primary gate']}
    train.write_new(out,result)
    print(json.dumps({'status':'EVALUATED_ONCE','output':str(out),'sha256':train.sha(out)}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('freeze','freeze-sha','training-commit','freeze-commit','eval-commit','extraction','transfer-manifest','transfer-manifest-sha','output'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--evaluation-authorized',action='store_true')
    run(p.parse_args())

if __name__=='__main__': main()
