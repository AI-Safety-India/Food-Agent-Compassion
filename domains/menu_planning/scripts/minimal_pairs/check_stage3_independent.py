"""Independent small raw-output recomputation; imports no primary analysis code."""
import argparse,hashlib,json,math
from collections import defaultdict
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();root=Path(a.root)
rows=[json.loads(s) for s in (root/'stage3/run/raw.jsonl').read_text().splitlines()]
results=json.loads((root/'stage3/results.json').read_text())
g=defaultdict(list)
for r in rows:
    if r['phase']!='study' or r['alpha'] not in [-4,4]:continue
    def pa(v):
        x=v[0]-v[1]
        return 1/(1+math.exp(-x)) if x>=0 else math.exp(x)/(1+math.exp(x))
    e=(pa(r['candidate_logits'])-pa(r['baseline_logits']))*(1 if r['target']=='A' else -1)
    g[(r['direction'],r['alpha'],r['set'],r['pair_id'])].append(e)
checks=[];saved={}
for alpha in [-4,4]:
    for name,sets in [('combined',{'welfare_train','welfare_heldout'}),('heldout',{'welfare_heldout'})]:
        pairs=sorted((pair,sum(v)/len(v)) for (d,al,s,pair),v in g.items() if d==0 and al==alpha and s in sets)
        assert all(len(v)==4 for (d,al,s,pair),v in g.items() if d==0 and al==alpha and s in sets)
        values=np.array([v for pair,v in pairs]);mean=float(values.mean())
        draws=np.random.default_rng(20261114).integers(0,len(values),(10000,len(values)))
        ci=np.percentile(values[draws].mean(axis=1),[2.5,97.5]).tolist()
        expected=results['primary'][name]['both']['effects'][str(alpha)]
        checks.extend([abs(mean-expected['mean'])]+[abs(x-y) for x,y in zip(ci,expected['ci95'])])
        saved[f'{name}_{alpha}']={'mean':mean,'ci95':ci,'n_pairs':len(values)}
    effects=[]
    for d in range(2,12):
        values=[sum(v)/len(v) for (di,al,s,pair),v in sorted(g.items()) if di==d and al==alpha and s=='welfare_heldout']
        assert len(values)==50
        effects.append(abs(sum(values)/50))
    ordered=sorted(effects);q=ordered[8]+.1*(ordered[9]-ordered[8])
    checks.append(abs(q-results['criteria']['combined']['doses'][str(alpha)]['random_abs_p90']))
    saved[f'random_p90_{alpha}']=q
assert max(checks)<1e-12,checks
out=root/'stage3/independent.json'
with out.open('x',encoding='utf-8') as f:
    json.dump({'status':'PASS','fields_compared':len(checks),'max_absolute_difference':max(checks),
        'recomputed':saved,'source_sha256':hashlib.sha256((root/'stage3/run/raw.jsonl').read_bytes()).hexdigest(),
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},f,indent=2)
print('INDEPENDENT_PASS',len(checks),'fields; max difference',max(checks))
