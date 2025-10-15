#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

def md5sum(path: Path) -> str:
    h = hashlib.md5()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def read_as_base64(path: Path) -> str:
    with path.open('rb') as f:
        return base64.b64encode(f.read()).decode('ascii')

def post_json(url: str, headers: dict, payload: dict, retries: int = 3, backoff: float = 1.5) -> dict:
    data = json.dumps(payload).encode('utf-8')
    for attempt in range(1, retries + 1):
        req = Request(url, data=data, headers=headers, method='POST')
        try:
            with urlopen(req, timeout=60) as resp:
                body = resp.read()
                return json.loads(body.decode('utf-8') or '{}')
        except (HTTPError, URLError) as e:
            if attempt == retries:
                raise
            time.sleep(backoff ** attempt)
    return {}

def format_ignored_msg(ignored: dict) -> str:
    # ignored is expected to be a mapping {name: reason}
    lines = []
    for k, v in (ignored or {}).items():
        lines.append(f'- **{k}**: {v}\n')
    return ''.join(lines)

def write_github_output(values: dict) -> None:
    path = os.environ.get('GITHUB_OUTPUT')
    if not path:
        return
    with open(path, 'a', encoding='utf-8') as fh:
        for k, v in values.items():
            if isinstance(v, str) and '\n' in v:
                fh.write(f'{k}<<EOF\n{v}EOF\n')
            else:
                fh.write(f'{k}={v}\n')

def main() -> int:
    parser = argparse.ArgumentParser(description='Validate or push templates.zip to Rave manage API')
    parser.add_argument('mode', choices=['validate', 'push'], help='validate or push')
    parser.add_argument('--host', required=True, help='host, e.g. manage-dev.ravesocial.co')
    parser.add_argument('--api-key', required=True, help='API key string for Auth-Token header')
    parser.add_argument('--zip-path', default='templates.zip', help='path to templates zip')
    args = parser.parse_args()

    zip_path = Path(args.zip_path)
    if not zip_path.is_file():
        print(f'File not found: {zip_path}', file=sys.stderr)
        return 2

    md5 = md5sum(zip_path)
    b64 = read_as_base64(zip_path)
    payload = {
        'file': {
            'filename': zip_path.name,
            'md5': md5,
            'data': b64,
        }
    }

    base = f'https://{args.host}'
    url = f'{base}/api/templates/zip/validate' if args.mode == 'validate' else f'{base}/api/templates/zip'
    headers = {
        'Content-Type': 'application/json',
        'Auth-Token': args.api_key,
    }

    try:
        resp = post_json(url, headers, payload)
    except Exception as e:
        print(f'HTTP error: {e}', file=sys.stderr)
        return 1

    print(json.dumps(resp, indent=2, ensure_ascii=False))

    if args.mode == 'validate':
        ignored = (resp or {}).get('data', {}).get('ignored') or {}
        has_ignored = bool(ignored)
        ignored_msg = format_ignored_msg(ignored)
        write_github_output({
            'has_ignored': 'true' if has_ignored else 'false',
            'ignored_msg': ignored_msg,
        })
    else:
        status = str((resp or {}).get('status')).lower() == 'true'
        if not status:
            print('Deployment failed.', file=sys.stderr)
            return 1

    return 0

if __name__ == '__main__':
    sys.exit(main())
