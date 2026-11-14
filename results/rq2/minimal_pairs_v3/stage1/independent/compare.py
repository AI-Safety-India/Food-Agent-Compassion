"""Compare independent headline tree to primary, requiring exact decisions/counts.
Independent floats may differ by <=1e-10 absolute from arithmetic ordering.
"""
import argparse,json,math
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--independent',required=True);p.add_argument('--primary',required=True);p.add_argument('--output',required=True);a=p.parse_args()
i=json.loads(Path(a.independent).read_text());s=json.loads(Path(a.primary).read_text());checks=[];failures=[]
def compare(x,y,path):
 if isinstance(x,dict):
  for k,v in x.items():
   if k=='provenance':continue
   if k not in y:failures.append({'path':path+'.'+k,'error':'missing primary key'})
   else:compare(v,y[k],path+'.'+k)
 elif isinstance(x,list):
  if len(x)!=len(y):failures.append({'path':path,'error':'length mismatch'})
  else:
   for k,(u,v) in enumerate(zip(x,y)):compare(u,v,path+f'[{k}]')
 elif isinstance(x,bool) or x is None or isinstance(x,int):
  checks.append({'path':path,'kind':'exact','equal':x==y})
  if x!=y:failures.append({'path':path,'independent':x,'primary':y})
 elif isinstance(x,float):
  delta=abs(x-y);checks.append({'path':path,'kind':'float','abs_difference':delta})
  if not math.isfinite(delta) or delta>1e-10:failures.append({'path':path,'independent':x,'primary':y,'abs_difference':delta})
 else:
  if x!=y:failures.append({'path':path,'independent':x,'primary':y})
compare(i,s,'result')
d={'pass':not failures,'absolute_float_tolerance':1e-10,'comparisons':len(checks),'max_absolute_difference':max([x['abs_difference'] for x in checks if x['kind']=='float'],default=0),'failures':failures,'checks':checks}
with Path(a.output).open('x') as f:json.dump(d,f,indent=2,allow_nan=False)
print(json.dumps({k:v for k,v in d.items() if k!='checks'}))
if failures:raise SystemExit(1)
