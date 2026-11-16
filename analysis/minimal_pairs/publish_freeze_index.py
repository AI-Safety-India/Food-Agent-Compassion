"""Expose the canonical frozen bundle at the plan's root manifest path."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[4]/'results/rq2/minimal_pairs_v3'
bundle=root/'stage1/frozen'
raw=(bundle/'FROZEN.json').read_bytes()
f=json.loads(raw)
cv=json.loads((bundle/'cv.json').read_text())
index={**f,'canonical_bundle':'stage1/frozen','canonical_manifest':'stage1/frozen/FROZEN.json',
       'canonical_manifest_sha256':hashlib.sha256(raw).hexdigest(),
       'files':{'stage1/frozen/'+name:digest for name,digest in f['files'].items()},
       'usage':'Evaluation consumes canonical_bundle with the externally recorded canonical_manifest_sha256 and freeze commit.'}
with (root/'FROZEN.json').open('x',encoding='utf-8',newline='\n') as h:json.dump(index,h,indent=2)
log=root/'stage1/training_verified_helper.log'
summary={'primary':{k:v for k,v in cv['selected_primary'].items() if k!='folds'},
         'secondary':{k:v for k,v in cv['selected_secondary'].items() if k!='folds'},
         'canonical_freeze_sha256':hashlib.sha256(raw).hexdigest(),'training_code_commit':f['code_commit'],
         'training_rows':len(f['train_prompt_ids']),'heldout_activation_values_opened':False,
         'training_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
         'new_model_forwards':0,'threads':1,'status':'TRAINED_NOT_EVALUATED'}
with (root/'stage1/TRAINING_SUMMARY.json').open('x',encoding='utf-8',newline='\n') as h:json.dump(summary,h,indent=2)
print(json.dumps(summary))
