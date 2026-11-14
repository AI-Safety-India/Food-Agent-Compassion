from pathlib import Path
import base64, gzip, hashlib, json
root = Path('/marimo/results/rq2/minimal_pairs_v3/transport_parts/dffff8f6a45f3abaf69c2b5f291952d940a3539debadd4e52108d9a923b3cd9b')
root.mkdir(parents=True, exist_ok=True)
p = root / '2'
data = '4/X4Vkt/wefbMH8lw+oz35MzVizHRxuhQAkN4IVj3emtcy+o4Fm1/40UjHGPSvM6qcf/Wh42Fz004w669BqA2gLkyjzhkx230aXXINQhWXMHhY418+ulmocVr/QEpC1k+UPEmr0bG0BVIwPASl3ycXZmGDxYAE46MVgLR4RBUx2vmrdaQV4R/Uh/WpEjHlbsqj+rVonmzURVXRzx5Rry8xMcXcD/Cy4r+j+MCz94/TdWFfFGib7z1cevv84fFhpTBjXuqyvga6SyuBwWiQ6I87jNroCvmhpwtlIjOhjImV/X1VvWaTH269BeecvX0jPo49gCZjVOAEzXLS1nRfWCwgzAcyfHbKG6XjCMx2vtrdZapz3OJNnipwI/4wLnW5e5H34iZZWcB5B/w9kmRSwlnOItiaY1lnqaEn4XtV8kun4R9ssZqtg5ZlRGu2Sf0P/2n0nKah3uIjo/aa4mlg1B8WPIttk20Gu0eY8y0XFzdgPVbkVpNa7OqkrPSRDjNu5GEHZrUBsLwkId6vmoIfNu+HqLVUPiYtXcq0Kk/d46gtiqSNSAwvD7SbC6svtZ6QGG3fvSg7nbz0YM43UDV194De8lytaMpq3WLeQqZqDeYPwcZQn9Co9QlKeUTrLYJCyqXki0L0h9Klmjz6Qu7qs/vt7YS5FQcCzlCf9ovDHWFmb3KpVpjlv9F75DeydMp8hSH6wYxn3+C99h/VRisJuYPlAlZN5NXm+RbrwUu26RKnv9H9tUhhpMGB4/GVJ3mT5noAUYFu9TCzZSgQYuhPEqhKsvga/Sj1yh16og292LPLADPhuSsDM/zRGgrvPzOtvQFk70m/Ha67xvEe/+ZvoU3WrH3GpJvtke218ZtJlfBi2q0Ry3+C/hr9ArMXWdDmMGYhj3+C/hr86bisFehozglZB5N3m9Jbux4vBaSTPsdn9sVR5qMGF4/ARIneXRmI8WYFi8Hy1YSK0RoBD+P0A1lrgjjQcA'
if p.exists():
    assert p.read_text() == data
else:
    with p.open('x') as f: f.write(data)
print('Verified upload fragment', 0, 2)
if all((root / str(i)).exists() for i in range(3)):
    complete = gzip.decompress(base64.b64decode(''.join((root / str(i)).read_text() for i in range(3))))
    assert hashlib.sha256(complete).hexdigest() == 'dffff8f6a45f3abaf69c2b5f291952d940a3539debadd4e52108d9a923b3cd9b'
    target = Path('/marimo/results/rq2/minimal_pairs_v3/inputs/prompts.jsonl')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == complete
    else:
        with target.open('xb') as f: f.write(complete)
    print(json.dumps({'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'bytes': len(complete)}))
