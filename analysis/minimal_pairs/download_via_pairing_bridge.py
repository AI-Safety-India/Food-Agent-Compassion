"""Authenticated result transfer through the unchanged existing pairing bridge.

No credential file is opened by this wrapper. The bridge supplies its normal
private environment to one intercepted transport invocation. Never log that
environment, bearer header, or transient file URLs.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import runpy
import sys
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[4]
ROOT = REPO / 'results/rq2/minimal_pairs_v3'
ENDPOINT = 'https://sb-8e189fdea7da37de.sb.molab.run/'
HOST = urllib.parse.urlsplit(ENDPOINT).hostname


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(4 * 1024**2), b''):
            h.update(part)
    return h.hexdigest()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    items = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    bridge = REPO.parent / 'rq2_repair/connect_molab.py'
    invoked = False

    def intercept(command, *, env, **kwargs):
        nonlocal invoked
        if invoked or command[-2:] != ['-c', 'import marimo._code_mode as cm; help(cm)']:
            raise RuntimeError('Unexpected bridge invocation')
        if command[2:4] != ['--url', ENDPOINT] or not command[1].endswith('execute-code.sh'):
            raise RuntimeError('Unexpected bridge endpoint/transport')
        invoked = True
        opener = urllib.request.build_opener(NoRedirect())
        for item in items:
            url = urllib.parse.urljoin(ENDPOINT, item['url'])
            parsed = urllib.parse.urlsplit(url)
            query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
            file_api = (parsed.path == '/api/files/download' and set(query) == {'path'}
                        and len(query['path']) == 1
                        and PurePosixPath(query['path'][0]).is_relative_to('/marimo/results/rq2/minimal_pairs_v3')
                        and '..' not in PurePosixPath(query['path'][0]).parts)
            if (parsed.scheme != 'https' or parsed.hostname != HOST or parsed.port not in (None, 443)
                    or parsed.username or parsed.password or parsed.fragment or not file_api):
                raise RuntimeError('Unapproved result URL')
            target = (ROOT / item['target']).resolve()
            if not target.is_relative_to(ROOT.resolve()):
                raise RuntimeError('Result destination outside task output')
            if target.exists():
                if target.stat().st_size == item['bytes'] and sha(target) == item['sha256']:
                    print('Verified existing', item['target'], flush=True)
                    continue
                raise RuntimeError('Existing destination differs; preserved')
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + '.partial')
            attempt = 0
            while partial.exists():
                attempt += 1
                partial = target.with_name(target.name + f'.partial.retry{attempt}')
            if attempt:
                print('Preserved interrupted transfer; retrying file only', item['target'], flush=True)
            request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + env['MARIMO_TOKEN'],
                                                          'User-Agent': 'marimo-pair-results/1.0'})
            h, total = hashlib.sha256(), 0
            try:
                with opener.open(request, timeout=120) as response, partial.open('xb') as f:
                    if response.status != 200:
                        raise RuntimeError('Unexpected HTTP status')
                    for data in iter(lambda: response.read(1024**2), b''):
                        total += len(data)
                        if total > item['bytes']:
                            raise RuntimeError('Response exceeds expected size')
                        h.update(data)
                        f.write(data)
            except urllib.error.HTTPError as error:
                body = error.read(1000).decode(errors='replace').replace(env['MARIMO_TOKEN'], '[redacted]')
                labels = [word for word in ['ROBOTS_DENIED', 'Forbidden', 'CSRF', 'Access Denied', 'Unauthorized', 'proxy', 'token', 'scope'] if word.lower() in body.lower()]
                import re
                diagnostic = re.sub(r'https?://\S+', '[URL]', body[:200]) if not labels else str(labels)
                raise RuntimeError(f'Result download HTTP status {error.code}; diagnostic={diagnostic}') from None
            except Exception as error:
                raise RuntimeError(f'Result download stopped ({type(error).__name__}); partial preserved') from None
            if total != item['bytes'] or h.hexdigest() != item['sha256']:
                raise RuntimeError('Result hash/size mismatch; partial preserved')
            partial.rename(target)
            print('Downloaded and verified', item['target'], total, flush=True)
        class Completed:
            stdout = io.StringIO('Authenticated result transfer complete.\n')
            def wait(self):
                return 0
        return Completed()

    original_argv = sys.argv
    try:
        sys.argv = [str(bridge), '--url', ENDPOINT]
        with patch('subprocess.Popen', intercept):
            runpy.run_path(str(bridge), run_name='__main__')
    finally:
        sys.argv = original_argv


if __name__ == '__main__':
    main()
