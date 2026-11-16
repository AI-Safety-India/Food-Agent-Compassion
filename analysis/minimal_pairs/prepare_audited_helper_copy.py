"""Preserve the original helper; copy its exact committed LF bytes for strict gates."""
from pathlib import Path
import ast, hashlib, json, subprocess
repo=Path(__file__).resolve().parents[4]
relative='domains/menu_planning/scripts/rq2/run_rq2_gpu_pipeline.py'
original=(repo/relative).read_bytes()
commit='6d432d568df7690117254bf65c573ebd04779b1a'
committed=subprocess.check_output(['git','show',commit+':'+relative],cwd=repo)
assert original.replace(b'\r\n',b'\n')==committed
assert ast.dump(ast.parse(original.decode()))==ast.dump(ast.parse(committed.decode()))
target=Path(__file__).with_name('audited_helper_lf.py')
with target.open('xb') as f:f.write(committed)
record={'original':relative,'original_sha256':hashlib.sha256(original).hexdigest(),
        'copy':target.relative_to(repo).as_posix(),'copy_sha256':hashlib.sha256(committed).hexdigest(),
        'source_commit':commit,'difference':'CRLF checkout versus exact committed LF bytes only',
        'ast_identical':True,'original_edited':False,'training_fits_before_fix':0}
with (repo/'results/rq2/minimal_pairs_v3/preflight/HELPER_NEWLINE_ADAPTER.json').open('x') as f:json.dump(record,f,indent=2)
print(json.dumps(record))
