"""Verify completed transfer/provenance and NPY headers without reading activations."""
from pathlib import Path
import hashlib, json, zipfile
from collections import Counter
import numpy as np

REPO = Path(__file__).resolve().parents[4]
ROOT = REPO/'results/rq2/minimal_pairs_v3'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024**2),b''): h.update(chunk)
    return h.hexdigest()


def main():
    transfer=json.loads((ROOT/'TRANSFER_MANIFEST.json').read_text())
    for item in transfer:
        p=ROOT/item['target']
        assert p.stat().st_size==item['bytes'] and sha(p)==item['sha256'], item['target']
    extraction=ROOT/'extraction'
    complete=json.loads((extraction/'COMPLETE.json').read_text())
    assert complete['rows']==1002 and complete['integrity_passed']
    headers=[]
    for layer in range(1,33):
        p=extraction/f'layer_{layer:02d}.npz'
        assert sha(p)==complete['files'][p.name]
        with zipfile.ZipFile(p) as z, z.open('activations.npy') as f:
            version=np.lib.format.read_magic(f)
            assert version in ((1,0),(2,0))
            reader=np.lib.format.read_array_header_1_0 if version==(1,0) else np.lib.format.read_array_header_2_0
            shape,fortran,dtype=reader(f)
        assert shape==(1002,5,4096) and dtype==np.dtype('float16') and not fortran
        headers.append({'layer':layer,'shape':shape,'dtype':str(dtype)})
    rows=[json.loads(s) for s in (extraction/'index.jsonl').read_text().splitlines()]
    events=[json.loads(s) for s in (extraction/'ledger.jsonl').read_text().splitlines()]
    counts=Counter((e['phase'],e['state']) for e in events)
    assert counts['main','intent']==counts['main','complete']==1002
    assert counts['integrity','intent']==counts['integrity','complete']==20
    assert len([r for r in rows if 'greedy_ids' in r])==30
    integrity=json.loads((extraction/'integrity.json').read_text())
    assert len(integrity['checks'])==20 and all(c['same_choice'] and c['same_greedy'] for c in integrity['checks'])
    corr=float(np.corrcoef(np.array([c['original'] for c in integrity['checks']]).ravel(),np.array([c['recomputed'] for c in integrity['checks']]).ravel())[0,1])
    assert corr>.999 and corr==integrity['correlation']
    provenance_count=0
    with zipfile.ZipFile(ROOT/'export/provenance.zip') as z:
        for name in z.namelist():
            if name.startswith('shards/'):
                assert hashlib.sha256(z.read(name)).hexdigest()==complete['files'][name]
                provenance_count+=1
        log=z.read('jobs/extract/worker.log').decode(errors='replace')
        warnings=[line[:500] for line in log.splitlines() if any(s in line.lower() for s in ['newly initialized','missing keys','unexpected keys'])]
        assert json.loads(z.read('jobs/extract/exit.json'))['returncode']==0
    training=json.loads((ROOT/'TRAIN_TRANSFER_MANIFEST.json').read_text())[0]
    trainzip=ROOT/training['target']
    assert sha(trainzip)==training['sha256'] and trainzip.stat().st_size==training['bytes']
    dest=ROOT/'train_inputs'
    assert not dest.exists(), 'Existing training files preserved'
    with zipfile.ZipFile(trainzip) as z:
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['source_complete_sha256']==sha(extraction/'COMPLETE.json')
        assert manifest['source_prompts_sha256']==sha(REPO.parent/'welfare_minimal_pairs/v3/prompts.jsonl')
        assert manifest['extraction_script_sha256']==json.loads((extraction/'identity.json').read_text())['script']
        assert set(z.namelist())==set(manifest['files'])|{'manifest.json'}
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
            if name.startswith('shards/'):
                assert complete['files'][name]==digest
        for name in z.namelist():
            assert (dest/name).resolve().is_relative_to(dest.resolve())
        dest.mkdir()
        z.extractall(dest)
    result={'status':'PASS','downloaded_files':len(transfer),'downloaded_bytes':sum(x['bytes'] for x in transfer),
            'layers':headers,'prompts':1002,'integrity_rechecks':20,'correlation':corr,'choices_identical':True,
            'main_attempts':1002,'calibration_three_token_diagnostics':30,'planned_total_forwards':1082,
            'provenance_shard_text_files_verified':provenance_count,'weight_loading_warning_lines':warnings,
            'training_only_rows':manifest['rows'],'heldout_or_neutral_activation_values_opened':False,
            'duplicate_sharded_activation_arrays':'retained remotely; hashes in COMPLETE; consolidated32arrays downloaded'}
    with (ROOT/'EXTRACTION_VERIFICATION.json').open('x') as f: json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='layers'}))


if __name__=='__main__':main()
