"""Copy only train/none shards for leakage-safe local fitting; no array inspection."""
from pathlib import Path
import hashlib, json, zipfile, urllib.parse
root = Path('/marimo/results/rq2/minimal_pairs_v3')
extraction = root/'extraction'
done = json.loads((extraction/'COMPLETE.json').read_text())
assert done['rows'] == 1002 and done['integrity_passed']
records = [json.loads(s) for s in (extraction/'index.jsonl').read_text().splitlines()]
selected=[]
files={}
for i,row in enumerate(records):
    if row['set'] == 'welfare_train' and row['condition'] == 'none':
        name = f'shards/{i:04d}.npz'
        selected.append({**row,'source_row':i,'shard_file':name,'shard_sha256':done['files'][name]})
        files[name]=done['files'][name]
assert len(selected) == 140
index = ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in selected).encode()
files['index.jsonl']=hashlib.sha256(index).hexdigest()
manifest={'rows':140,'files':files,'source_complete_sha256':hashlib.sha256((extraction/'COMPLETE.json').read_bytes()).hexdigest(),
          'source_prompts_sha256':hashlib.sha256((root/'inputs/prompts.jsonl').read_bytes()).hexdigest(),
          'extraction_script_sha256':json.loads((extraction/'identity.json').read_text())['script']}
archive=root/'export/train_inputs.zip'
assert not archive.exists(), 'Existing training export preserved'
with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
    z.writestr('index.jsonl',index)
    z.writestr('manifest.json',json.dumps(manifest,indent=2))
    for row in selected:
        p=extraction/row['shard_file']
        assert hashlib.sha256(p.read_bytes()).hexdigest()==row['shard_sha256']
        z.write(p,row['shard_file'])
sha=hashlib.sha256(archive.read_bytes()).hexdigest()
item={'target':'export/train_inputs.zip','url':'/api/files/download?'+urllib.parse.urlencode({'path':str(archive)}),
      'bytes':archive.stat().st_size,'sha256':sha}
print('TRAIN_DOWNLOAD_JSON',json.dumps([item]))
print('TRAIN_ROWS',len(selected))
