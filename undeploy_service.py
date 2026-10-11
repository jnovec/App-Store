#!/usr/bin/env python3
import json
import os
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

DATA = Path('/data')
JOBS = DATA / 'jobs'
REGISTRY = DATA / 'deployments.json'
SECRET_FILE = DATA / 'deploy-agent-secret.txt'
HOST = '0.0.0.0'
PORT = 18792
LOCK = threading.RLock()


def job_path(job_id):
    return JOBS / f'{job_id}.json'


def save_job(job):
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = job_path(job['id']).with_suffix('.tmp')
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    tmp.replace(job_path(job['id']))


def load_job(job_id):
    path = job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def append_log(job, line):
    line = str(line).rstrip()
    if not line:
        return
    with LOCK:
        job.setdefault('log', []).append(line)
        job['log'] = job['log'][-500:]
        job['updated_at'] = int(time.time())
        save_job(job)


def load_registry():
    if not REGISTRY.exists():
        return {}
    try:
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_registry(data):
    REGISTRY.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def run_job(job):
    with LOCK:
        job['status'] = 'running'
        job['started_at'] = int(time.time())
        job['updated_at'] = int(time.time())
        save_job(job)

    hostname = job['hostname']
    purge_data = bool(job.get('purge_data'))
    try:
        registry = load_registry()
        item = registry.get(hostname)
        if not isinstance(item, dict):
            raise RuntimeError('DEPLOYMENT_NOT_FOUND')

        container = str(item.get('container') or '').strip()
        append_log(job, f'[1/4] Removing container {container or "(unknown)"}…')
        if container:
            inspect = subprocess.run(['docker', 'inspect', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if inspect.returncode == 0:
                subprocess.run(['docker', 'rm', '-f', container], check=True)
            else:
                append_log(job, 'Container is already absent.')

        append_log(job, '[2/4] Persistent data policy: ' + ('DELETE volumes' if purge_data else 'KEEP volumes'))
        removed_volumes = []
        if purge_data and container:
            try:
                names = subprocess.check_output(['docker', 'volume', 'ls', '--format', '{{.Name}}'], text=True).splitlines()
            except Exception:
                names = []
            prefixes = (f'{container}-data', f'{container}_data')
            for volume in names:
                if any(volume == prefix or volume.startswith(prefix + '-') for prefix in prefixes):
                    subprocess.run(['docker', 'volume', 'rm', volume], check=False)
                    removed_volumes.append(volume)
                    append_log(job, 'Removed volume: ' + volume)

        append_log(job, '[3/4] Removing deployment from NOVEC registry…')
        registry.pop(hostname, None)
        save_registry(registry)

        append_log(job, '[4/4] Hostname released for reuse by NOVEC App Store.')
        result = {
            'ok': True,
            'action': 'undeploy',
            'hostname': hostname,
            'url': f'https://{hostname}',
            'container': container,
            'purge_data': purge_data,
            'removed_volumes': removed_volumes,
            'hostname_reusable': True,
        }
        append_log(job, json.dumps(result, ensure_ascii=False))
        with LOCK:
            job['status'] = 'success'
            job['result'] = result
            job['error'] = None
            job['finished_at'] = int(time.time())
            job['updated_at'] = int(time.time())
            save_job(job)
    except Exception as exc:
        append_log(job, f'ERROR: {exc}')
        with LOCK:
            job['status'] = 'error'
            job['error'] = str(exc)
            job['finished_at'] = int(time.time())
            job['updated_at'] = int(time.time())
            save_job(job)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def authorized(self):
        expected = SECRET_FILE.read_text(encoding='utf-8').strip() if SECRET_FILE.exists() else ''
        supplied = self.headers.get('X-NOVEC-Agent-Secret', '')
        return bool(expected and supplied == expected)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/health':
            self.send_json(200, {'ok': True, 'mode': 'async', 'service': 'undeploy'})
            return
        if path.startswith('/job/'):
            if not self.authorized():
                self.send_json(403, {'ok': False, 'error': 'FORBIDDEN'})
                return
            job = load_job(path.rsplit('/', 1)[-1])
            if not job:
                self.send_json(404, {'ok': False, 'error': 'JOB_NOT_FOUND'})
                return
            self.send_json(200, job)
            return
        self.send_json(404, {'ok': False, 'error': 'NOT_FOUND'})

    def do_POST(self):
        if urlparse(self.path).path != '/undeploy':
            self.send_json(404, {'ok': False, 'error': 'NOT_FOUND'})
            return
        if not self.authorized():
            self.send_json(403, {'ok': False, 'error': 'FORBIDDEN'})
            return
        try:
            length = min(int(self.headers.get('Content-Length', '0')), 8192)
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            hostname = str(payload.get('hostname', '')).strip().lower()
            purge_data = bool(payload.get('purge_data', False))
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.novec\.online', hostname):
                raise ValueError('INVALID_HOSTNAME')
        except Exception:
            self.send_json(400, {'ok': False, 'error': 'INVALID_JSON'})
            return

        job_id = uuid.uuid4().hex[:16]
        now = int(time.time())
        job = {
            'id': job_id,
            'action': 'undeploy',
            'hostname': hostname,
            'purge_data': purge_data,
            'status': 'queued',
            'created_at': now,
            'updated_at': now,
            'started_at': None,
            'finished_at': None,
            'result': None,
            'error': None,
            'log': ['Removal queued.'],
        }
        save_job(job)
        threading.Thread(target=run_job, args=(job,), daemon=True).start()
        self.send_json(202, {'ok': True, 'job_id': job_id, 'status': 'queued'})


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'NOVEC undeploy service listening on {HOST}:{PORT}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
