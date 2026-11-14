from pathlib import Path
import base64, gzip, hashlib, json
for item in [{'path': '/marimo/domains/menu_planning/scripts/minimal_pairs/job_supervisor.py', 'sha256': '5def3411ff023bed71fd4063d0e569f4c1226c774a948fbdf1c8aaee5ca44027', 'data': 'H4sIAAAAAAACCqVVS4/bOAy++1cIucguYnvbvU2RQ6cToLtYNINBgKIYDATFpmN1bEmrx8wERf97KfmVbBctsKtDIpHUR/KjSK9Wqxtv+KEDYv1BG1WBtQRehCPwJGqQFRTkL+5l1aKUV647EYVC4lqj/LHFfyBSOTgo9VisVqtE9FoZR7g5am4sTOcvVslpr2zSGNUTzV3biQMZxbd4nEyWYGbJad46wys48OoxSe52uz3ZxKspLXtuRK9KA9Z3zpbm7zdlL6Toecc0F8ayp99plrzf3Wx/uFOrngtpyx6kZ7rjUgp5LG1lhEakCxSESJIaGhJupNlVQnDFZA3CTokX78zRI5q7jZo0OzMreF0zPupTah0/Al2TqlUCU97cU20ALYOMwktI19GHAQBvWfQy4sS/gGRH/C/qgNrISkkonizFTTAoopdo5PAMDu2CdRlcCFeEAtGoFs1oUaDCOjulGJbhwgK589KJHrbGKJPSPxGFdwZ4fSINEmVbqN/ioyC1152ouAPSxRdEhxidOS2A6GyJjmw2ZM59sQmrUn3PZY1B3+NLwMig8i68W6Qovw5E5R5/rTNprG85AzFuLThb6BPNHmZM6CxcekB40YB1Z/wNCNwJJUsrubatcmyyO2NsWpNNoBaVRad4bdP5QqCIOSxommX3dDKmD/830fGJsItXGvNF62dlHsHQ9YWTs0XzHDutx1c+ok7JC6k9Pv1RGbPtIiJeiG3w7+bRd6Qm+5nPOfv1zNr6XJ5PrI1upuNPQVvodMj1gh3ua+GgZoNyoiXPlXcY8T+yGKkUvwr/uUVMq3EO5QflZc3NKZYmbwxAbob+yCslG2F6qM9qPAwnLO8y4gq0T8e6rwnIp83XV68U1l4+CaMk4t5+3n/YfbzZfdx/uvtjv73+vN+G9OgVoa/pt2wGxy5yPsyHr+NQuTrrLsQx4LyRlaqDZoikWGRoMAAEXIxHd+CAhhb9wTR06m+xiQhtuOgwxW8xCnipQDtyzS1s4xapvPpv8b2+iGf0grJ5/KN43heNMj13DP2n2RDKs3DtNMmUBpnSF5oRbkmzBBTbtPa9TgdPa9KsiZD44XObNwuvTdF03rbpIsHyNPYkqxRVGJhU2NNROTStcCPg/XlOD+HLgXQyJnkPjMV5x1j4jjA2Drzho5J8B8FNfdaZBwAA'}]:
    path = Path(item['path'])
    data = gzip.decompress(base64.b64decode(item['data']))
    assert hashlib.sha256(data).hexdigest() == item['sha256']
    if path.exists():
        assert path.read_bytes() == data, 'Existing destination differs; never overwrite'
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as f: f.write(data)
    print(json.dumps({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': len(data)}))
