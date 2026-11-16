"""Package provenance and describe completed files; never interpret activations."""
from pathlib import Path
import hashlib, json, zipfile
import urllib.parse

root = Path('/marimo/results/rq2/minimal_pairs_v3')
extraction = root / 'extraction'
done = json.loads((extraction / 'COMPLETE.json').read_text())
assert done['rows'] == 1002 and done['integrity_passed'] is True
assert json.loads((root/'jobs/extract/exit.json').read_text())['returncode'] == 0
exports = root / 'export'
exports.mkdir(exist_ok=True)
archive = exports/'provenance.zip'
if not archive.exists():
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted((extraction/'shards').iterdir()):
            if p.is_file() and p.suffix != '.npz':
                z.write(p, p.relative_to(extraction))
        for stage in ['prepare','prepare2','extract']:
            for p in sorted((root/'jobs'/stage).iterdir()):
                if p.is_file(): z.write(p, p.relative_to(root))
        for name in ['snapshot_manifest.json','RUNTIME_READY.json','EXTRACTION_APPROVAL.json','tokenizer_stdout.log']:
            p = root/'preparation'/name
            z.write(p,p.relative_to(root))

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024**2),b''): h.update(chunk)
    return h.hexdigest()

items=[]
paths = [p for p in sorted(extraction.iterdir()) if p.is_file() and p.name != 'worker.lock'] + [archive]
for p in paths:
    digest = sha(p)
    if p.parent == extraction and p.name != 'COMPLETE.json':
        assert done['files'][p.name] == digest
    items.append({'target':p.relative_to(root).as_posix(),'url':'/api/files/download?'+urllib.parse.urlencode({'path':str(p)}),
                  'bytes':p.stat().st_size,'sha256':digest})
destination=exports/'DOWNLOAD_MANIFEST.json'
if destination.exists():
    assert json.loads(destination.read_text())==items
else:
    with destination.open('x') as f: json.dump(items,f,indent=2)
print('DOWNLOAD_MANIFEST_JSON',json.dumps(items))
print('RESULT_COUNTS',json.dumps({'files':len(items),'bytes':sum(i['bytes'] for i in items),'rows':done['rows']}))
