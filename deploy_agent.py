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
HELPER = BASE / "deploy_helper.py"
HOST = "0.0.0.0"
PORT = 18791
LOCK = threading.RLock()


def job_path(job_id):
    return JOBS / f"{job_id}.json"


def save_job(job):
    JOBS.mkdir(parents=True, exist_ok=True)
    tmp = job_path(job['id']).with_suffix('.tmp')
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    tmp.replace(job_path(job['id']))


def recover_completed_job(job):
    if job.get('status') not in {'running', 'queued'}:
        return job
    for line in reversed(job.get('log') or []):
        text = str(line).strip()
        if not (text.startswith('{') and text.endswith('}')):
            continue
        try:
            candidate = json.loads(text)
        except Exception:
            continue
        if isinstance(candidate, dict) and candidate.get('ok') is True and candidate.get('url'):
            job['status'] = 'success'
            job['result'] = candidate
            job['error'] = None
            job['finished_at'] = job.get('finished_at') or int(time.time())
            job['updated_at'] = int(time.time())
            if not any('Deployment completed successfully.' in str(x) for x in (job.get('log') or [])):
                job.setdefault('log', []).append('Deployment completed successfully.')
            save_job(job)
            return job
    return job


def load_job(job_id):
    p = job_path(job_id)
    if not p.exists():
        return None
    try:
        job = json.loads(p.read_text(encoding='utf-8'))
        return recover_completed_job(job)
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


def run_job(job):
    with LOCK:
        job['status'] = 'running'
        job['started_at'] = int(time.time())
        job['updated_at'] = int(time.time())
        save_job(job)
    append_log(job, f"NOVEC deploy job {job['id']} started")
    append_log(job, f"App: {job['app_id']}  Host: {job['subdomain']}.novec.online")

    cmd = [sys.executable, str(HELPER), job['app_id'], job['subdomain'], job['template_key']]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        last_json = None
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip('\n')
            append_log(job, line)
            if line.startswith('{') and line.endswith('}'):
                try:
                    candidate = json.loads(line)
                    if isinstance(candidate, dict) and 'ok' in candidate:
                        last_json = candidate
                except Exception:
                    pass
        rc = proc.wait(timeout=5)
    except Exception as e:
        rc = -1
        last_json = {'ok': False, 'error': str(e)}
        append_log(job, f"ERROR: {e}")

    with LOCK:
        if rc == 0 and isinstance(last_json, dict) and last_json.get('ok'):
            job['status'] = 'success'
            job['result'] = last_json
            job['error'] = None
            append_log(job, 'Deployment completed successfully.')
        else:
            job['status'] = 'error'
            job['result'] = last_json if isinstance(last_json, dict) else None
            job['error'] = (last_json or {}).get('error', f'DEPLOY_FAILED_{rc}') if isinstance(last_json, dict) else f'DEPLOY_FAILED_{rc}'
            append_log(job, f"Deployment failed: {job['error']}")
        job['finished_at'] = int(time.time())
        job['updated_at'] = int(time.time())
        save_job(job)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def authorized(self):
        expected = SECRET_FILE.read_text(encoding="utf-8").strip() if SECRET_FILE.exists() else ""
        supplied = self.headers.get("X-NOVEC-Agent-Secret", "")
        return bool(expected and supplied == expected)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(200, {"ok": True, "mode": "async"})
            return
        if path.startswith('/job/'):
            if not self.authorized():
                self.send_json(403, {"ok": False, "error": "FORBIDDEN"})
                return
            job_id = path.rsplit('/', 1)[-1]
            job = load_job(job_id)
            if not job:
                self.send_json(404, {"ok": False, "error": "JOB_NOT_FOUND"})
                return
            self.send_json(200, job)
            return
        self.send_json(404, {"ok": False, "error": "NOT_FOUND"})

    def do_POST(self):
        if urlparse(self.path).path != "/deploy":
            self.send_json(404, {"ok": False, "error": "NOT_FOUND"})
            return
        if not self.authorized():
            self.send_json(403, {"ok": False, "error": "FORBIDDEN"})
            return

        try:
            length = min(int(self.headers.get("Content-Length", "0")), 8192)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            app_id = str(payload.get("app_id", "")).strip().lower()
            subdomain = str(payload.get("subdomain", "")).strip().lower()
            template_key = str(payload.get("template_key", app_id)).strip().lower()
            if not app_id or not subdomain or not template_key:
                raise ValueError('missing fields')
        except Exception:
            self.send_json(400, {"ok": False, "error": "INVALID_JSON"})
            return

        job_id = uuid.uuid4().hex[:16]
        now = int(time.time())
        job = {
            'id': job_id,
            'app_id': app_id,
            'subdomain': subdomain,
            'template_key': template_key,
            'status': 'queued',
            'created_at': now,
            'updated_at': now,
            'started_at': None,
            'finished_at': None,
            'result': None,
            'error': None,
            'log': ['Deployment queued.'],
        }
        save_job(job)
        threading.Thread(target=run_job, args=(job,), daemon=True).start()
        self.send_json(202, {"ok": True, "job_id": job_id, "status": "queued"})


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NOVEC deploy agent listening on {HOST}:{PORT} (async jobs)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
