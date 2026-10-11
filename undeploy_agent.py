#!/usr/bin/env python3
import json
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
JOBS = DATA / "jobs"
SECRET_FILE = DATA / "deploy-agent-secret.txt"
HELPER = BASE / "undeploy_helper.py"
HOST = "0.0.0.0"
PORT = 18792
LOCK = threading.RLock()


def job_path(job_id):
    return JOBS / f"{job_id}.json"


def save_job(job):
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = job_path(job['id']).with_suffix('.tmp')
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    tmp.replace(job_path(job['id']))


def append_log(job, line):
    line = str(line).rstrip()
    if not line:
        return
    with LOCK:
        job.setdefault('log', []).append(line)
        job['log'] = job['log'][-500:]
        job['updated_at'] = int(time.time())
        save_job(job)


def load_job(job_id):
    path = job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def run_job(job):
    with LOCK:
        job['status'] = 'running'
        job['started_at'] = int(time.time())
        save_job(job)
    append_log(job, f"NOVEC removal job {job['id']} started")
    append_log(job, f"Host: {job['hostname']}  Purge data: {'yes' if job.get('purge_data') else 'no'}")
    command = [sys.executable, str(HELPER), job['hostname'], '1' if job.get('purge_data') else '0']
    try:
        process = subprocess.Popen(command, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        last_json = None
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.rstrip('\n')
            append_log(job, line)
            if line.startswith('{') and line.endswith('}'):
                try:
                    candidate = json.loads(line)
                    if isinstance(candidate, dict) and 'ok' in candidate:
                        last_json = candidate
                except Exception:
                    pass
        return_code = process.wait(timeout=5)
    except Exception as exc:
        return_code = -1
        last_json = {'ok': False, 'error': str(exc)}
        append_log(job, f"ERROR: {exc}")

    with LOCK:
        if return_code == 0 and isinstance(last_json, dict) and last_json.get('ok'):
            job['status'] = 'success'
            job['result'] = last_json
            job['error'] = None
            append_log(job, 'Removal completed successfully.')
        else:
            job['status'] = 'error'
            job['result'] = last_json if isinstance(last_json, dict) else None
            job['error'] = (last_json or {}).get('error', f'REMOVAL_FAILED_{return_code}') if isinstance(last_json, dict) else f'REMOVAL_FAILED_{return_code}'
            append_log(job, f"Removal failed: {job['error']}")
        job['finished_at'] = int(time.time())
        job['updated_at'] = int(time.time())
        save_job(job)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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
            if not hostname:
                raise ValueError('hostname missing')
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
        self.send_json(202, {'ok': True, 'job_id': job_id, 'status': 'queued', 'action': 'undeploy'})


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NOVEC undeploy agent listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
