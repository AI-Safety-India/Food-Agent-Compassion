"""Prospective Stage1 evaluation primitives. No automatic data reads or fitting.
Caller must run verify_evaluation_freeze BEFORE opening any heldout arrays.
Arrays supplied to evaluate are [prompt, position(endA,endB,meanA,meanB), hidden]
at the separately frozen layer for each method. No layer/direction selection here.
"""
from collections import defaultdict
from pathlib import Path
import numpy as np
import train_stage1 as train

SEED = 20261114
N_BOOT = 10000
SPECIFICATION = {
 'primary': 'mass mean only determines Stage1 gate; logistic separately descriptive',
 'accuracy': 'strict better>worse per prompt, ties zero; mechanism bootstrap10000 primary, pair bootstrap secondary',
 'neutral': 'average signed line1-line2 over two orders per pair; mean absolute paired gap / mean paired heldout better-worse gap; denominator<=0 fails',
 'neutral_choice': 'audited AUROC over188 line rows; candidate-logit ties choose A; require AUROC<.60',
 'neutral_gate': 'signed pair bootstrap95% CI includes0; gap ratio<.25',
 'heldout_gate': 'accuracy>=.70 and mechanism bootstrap lower>.55',
 'baselines': 'char/token length both signs ties half; random single unit vector seed20261114;100 pair-label shuffles same flip both orders refit frozen-layer mass mean; BOW',
 'baseline_gate': 'primary exceeds every scalar baseline and shuffled mean by>=.10 AND exceeds shuffled95th percentile',
 'bow': "CountVectorizer(token_pattern=r'[a-z]+',binary=True), vocabulary train140 unique lines ONLY; LogisticRegression(C=1,max_iter=3000,random_state=20261114). Corrects original all-text vocabulary; historical .44 not assumed",
 'robustness': 'same end-trained frozen direction applied to meanA/B; no refit',
 'sensitivity': 'train-only frozen length residualizer/direction; partial correlations descriptive',
 'freeze': 'external FROZEN SHA, training code commit, committed freeze and eval source checked before any heldout arrays',
}

def verify_evaluation_freeze(root, expected_sha, training_commit, freeze_commit, eval_commit, repo):
    frozen = train.verify_frozen(root, expected_sha, training_commit, freeze_commit)
    train.verify_code_commit(eval_commit, [__file__], repo)
    return frozen

def paired(values, rows):
    groups = defaultdict(list)
    for value,row in zip(values,rows,strict=True): groups[row['pair_id']].append((row['mirrored'],float(value)))
    if any(len(v)!=2 or {x[0] for x in v}!={False,True} for v in groups.values()):
        raise ValueError('Exactly two distinct mirrored orders per pair required')
    return {k:sum(x[1] for x in v)/2 for k,v in sorted(groups.items())}

def gap(scores, rows, target='better'):
    scores=np.asarray(scores,dtype=float)
    if scores.shape != (len(rows),2) or not np.isfinite(scores).all(): raise ValueError('Invalid line scores')
    if any({r['A_is'],r['B_is']} != ({'better','worse'} if target=='better' else {'line_1','line_2'}) for r in rows):
        raise ValueError('Invalid target labels')
    return (scores[:,0]-scores[:,1])*np.array([1 if r['A_is']==target else -1 for r in rows])

def bootstrap(values, clusters, n=N_BOOT, seed=SEED):
    values=np.asarray(values,dtype=float)
    groups=defaultdict(list)
    for v,c in zip(values,clusters,strict=True): groups[c].append(v)
    if not groups or not np.isfinite(values).all(): raise ValueError('Invalid bootstrap input')
    # Resample whole clusters; preserve prompt weighting, including unequal cluster sizes.
    keys=sorted(groups); sums=np.array([sum(groups[k]) for k in keys]); sizes=np.array([len(groups[k]) for k in keys])
    ix=np.random.default_rng(seed).integers(0,len(keys),size=(n,len(keys)))
    draws=sums[ix].sum(axis=1)/sizes[ix].sum(axis=1)
    return [float(x) for x in np.quantile(draws,[.025,.975])]

def accuracy(scores,rows,half_ties=False):
    g=gap(scores,rows); win=(g>0).astype(float)+(g==0)*(.5 if half_ties else 0)
    return {'accuracy':float(win.mean()),'correct':int((g>0).sum()),'ties':int((g==0).sum()),'total':len(g),
            'mechanism_ci':bootstrap(win,[r['mechanism'] for r in rows]),
            'pair_ci':bootstrap(win,[r['pair_id'] for r in rows])}

def correlation(x,y):
    x,y=np.asarray(x,float),np.asarray(y,float)
    if np.std(x)<1e-12 or np.std(y)<1e-12: return None
    return float(np.corrcoef(x,y)[0,1])

def partial_correlation(x,y,controls):
    c=np.column_stack([np.ones(len(x)),controls]); x=np.asarray(x,float); y=np.asarray(y,float)
    return correlation(x-c@np.linalg.lstsq(c,x,rcond=None)[0],y-c@np.linalg.lstsq(c,y,rcond=None)[0])

def line_features(rows):
    texts=[[r['spans'][k+'_line']['text'] for k in ('A','B')] for r in rows]
    lengths=np.array([[len(r['spans'][k+'_line']['token_indices']) for k in ('A','B')] for r in rows])
    chars=np.array([[len(t) for t in pair] for pair in texts])
    return texts,lengths,chars

def neutral_analysis(scores,rows,heldout_scores,heldout_rows,helper):
    pg=paired(gap(scores,rows,'line_1'),rows); vals=list(pg.values())
    denom=float(np.mean(list(paired(gap(heldout_scores,heldout_rows),heldout_rows).values())))
    ci=bootstrap(vals,list(pg)); ratio=float(np.mean(np.abs(vals))/denom) if denom>0 else None
    # choice_score is calibrated logitA-logitB, previously identity-validated by Stage0.
    chosen=np.array([[int(r['choice_score']>=0),int(r['choice_score']<0)] for r in rows]).reshape(-1)
    auc=float(helper.compute_auroc(chosen,np.asarray(scores).reshape(-1)))
    texts,_,_=line_features(rows)
    lexical=[]
    for a,b in texts:
        aa,bb=set(a.lower().split()),set(b.lower().split()); lexical.append(1-len(aa&bb)/len(aa|bb))
    pd=paired(lexical,rows)
    return {'pairs':len(pg),'line_rows':len(chosen),'signed_gap':float(np.mean(vals)),'signed_ci':ci,
      'mean_absolute_paired_gap':float(np.mean(np.abs(vals))),'heldout_gap_denominator':denom,'gap_ratio':ratio,
      'choice_auroc':auc,'absolute_gap_lexical_jaccard_correlation':correlation(np.abs(vals),list(pd.values())),
      'passes':bool(ci[0]<=0<=ci[1] and ratio is not None and ratio<.25 and auc<.60)}

def shuffled_baseline(xtrain,train_rows,xheld,held_rows,helper):
    ids=sorted({r['pair_id'] for r in train_rows}); rng=np.random.default_rng(SEED); result=[]
    labels=np.array([[int(r[k+'_is']=='better') for k in ('A','B')] for r in train_rows])
    for _ in range(100):
        flips=dict(zip(ids,rng.integers(0,2,len(ids))))
        y=np.array([v ^ flips[r['pair_id']] for v,r in zip(labels,train_rows)]).reshape(-1)
        w,mid=helper.fit_mass_mean(xtrain.reshape(-1,xtrain.shape[-1]),y)
        sc=helper.score_mass_mean(xheld.reshape(-1,xheld.shape[-1]),w,mid).reshape(-1,2)
        result.append(float((gap(sc,held_rows)>0).mean()))
    return {'accuracies':result,'mean':float(np.mean(result)),'percentile95':float(np.quantile(result,.95))}

def evaluate_method(held_x,held_rows,neutral_x,neutral_rows,direction,intercept,helper):
    hs=held_x[:,:2]@direction+intercept; ns=neutral_x[:,:2]@direction+intercept
    return {'heldout':accuracy(hs,held_rows),'neutral':neutral_analysis(ns,neutral_rows,hs,held_rows,helper),
            'mean_position_same_direction':accuracy(held_x[:,2:4]@direction+intercept,held_rows)}

def evaluate_baselines(train_x,train_rows,held_x,held_rows,direction,helper,bow_artifact):
    _,tokens,chars=line_features(held_rows)
    out={}
    for name,x in [('characters',chars),('tokens',tokens)]:
        for sign in (-1,1): out[f'{name}_sign{sign}']=float(((gap(sign*x,held_rows)>0)+.5*(gap(sign*x,held_rows)==0)).mean())
    rng=np.random.default_rng(SEED); w=rng.normal(size=held_x.shape[-1]); w/=np.linalg.norm(w)
    out['random_direction']=float((gap(held_x@w,held_rows)>0).mean())
    bow={'accuracy':float((gap(frozen_bow_scores(bow_artifact,held_rows),held_rows)>0).mean()),'training_lines':140,'vocabulary_size':len(bow_artifact['vocabulary'])}; out['bag_of_words']=bow['accuracy']
    null=shuffled_baseline(train_x,train_rows,held_x,held_rows,helper)
    primary=float((gap(held_x@direction,held_rows)>0).mean())
    null['margin_vs_mean']=primary-null['mean']
    null['margin_vs_percentile95']=primary-null['percentile95']
    null['sensitivity_margin_at_least_point10_over_percentile95']=bool(primary-null['percentile95']>=.10-1e-12)
    null['sensitivity_is_report_only']=True
    return {'scalar_accuracy':out,'bow_details':bow,'shuffled':null,
            'passes':bool(all(primary-v>=.10-1e-12 for v in [*out.values(),null['mean']]) and primary>null['percentile95'])}

def primary_gate(primary,baselines):
    h=primary['heldout']; held= h['accuracy']>=.70 and h['mechanism_ci'][0]>.55
    passed=bool(held and baselines['passes'] and primary['neutral']['passes'])
    return {'heldout_passes':held,'stage1_passes':passed,'stage3_statistical_eligibility':passed,
      'interpretation':'passes prospective Stage1 criteria' if passed else ('separates welfare content but is contaminated' if held and not primary['neutral']['passes'] else 'Stage1 criteria not met')}

def validate_evaluation_rows(heldout_rows,neutral_rows):
    for rows,label,n,pairs,mechanisms in [(heldout_rows,'welfare_heldout',100,50,10),(neutral_rows,'neutral_control',94,47,None)]:
        if len(rows)!=n or len({r['prompt_id'] for r in rows})!=n or any(r['set']!=label or r['condition']!='none' for r in rows):
            raise ValueError('Wrong evaluation coverage/set/condition')
        groups=paired(np.zeros(n),rows)
        if len(groups)!=pairs or (mechanisms is not None and len({r['mechanism'] for r in rows})!=mechanisms):
            raise ValueError('Wrong evaluation pair/mechanism coverage')

def length_descriptives(scores,rows):
    _,tokens,_=line_features(rows)
    labels=np.array([[int(r[k+'_is']=='better') for k in ('A','B')] for r in rows]).reshape(-1)
    pos=np.tile([0,1],len(rows)); score=np.asarray(scores).reshape(-1); length=tokens.reshape(-1)
    return {'score_length_controlling_label_position':partial_correlation(score,length,np.column_stack([labels,pos])),
      'score_label_controlling_length_position':partial_correlation(score,labels,np.column_stack([length,pos]))}

def load_frozen_layer(path,expected_sha,layer,expected_rows=1002):
    """Caller invokes freeze guard first; verify array hash before np.load.
    Full source shape includes final; functions intentionally slice first4 positions.
    """
    if train.sha(path)!=expected_sha: raise ValueError('Activation file hash mismatch')
    with np.load(path,allow_pickle=False) as z:
        a=z['activations']
        if z['positions'].tolist()!=['endA','endB','meanA','meanB','final'] or int(z['layer'])!=layer:
            raise ValueError('Array positions/layer identity differs')
        if a.shape!=(expected_rows,5,4096) or a.dtype!=np.float16 or not np.isfinite(a).all():
            raise ValueError('Expected finite fp16[prompt,5,4096], positions endA/endB/meanA/meanB/final')
        return a.astype(np.float32)

def evaluate_length_adjusted(x,rows,artifact):
    _,tokens,_=line_features(rows)
    residual=x[:,:2]-artifact['residual_intercept']-tokens[:,:,None]*artifact['residual_slope']
    scores=residual@artifact['direction']
    # Constant midpoint/intercept cancels in every within-prompt comparison.
    return {'heldout':accuracy(scores,rows),'descriptive':length_descriptives(scores,rows)}

def frozen_bow_scores(artifact,rows):
    from sklearn.feature_extraction.text import CountVectorizer
    if artifact['binary'] is not True or artifact['token_pattern']!='[a-z]+' or artifact['lowercase'] is not True:
        raise ValueError('Frozen BOW recipe differs')
    vec=CountVectorizer(token_pattern=artifact['token_pattern'],binary=True,lowercase=True,vocabulary=artifact['vocabulary'])
    texts,_,_=line_features(rows)
    return (vec.transform([t for pair in texts for t in pair])@np.asarray(artifact['coefficient'])+artifact['intercept']).reshape(-1,2)
