#!/usr/bin/env python3
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
JOBS = DATA / "jobs"
BACKUPS = DATA / "backups"
DEPLOYMENTS = DATA / "deployments.json"
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
    if job.get('action') != 'deploy':
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


def executable(name, candidates=()):
    found = shutil.which(name)
    if found:
        return found
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def docker_bin():
    return executable('docker', [
        '/usr/local/bin/docker',
        '/opt/homebrew/bin/docker',
        '/Applications/Docker.app/Contents/Resources/bin/docker',
    ])


def docker_cmd(args, timeout=30, check=False):
    docker = docker_bin()
    if not docker:
        raise RuntimeError('DOCKER_NOT_FOUND')
    return subprocess.run([docker] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=check)


def load_registry():
    try:
        raw = json.loads(DEPLOYMENTS.read_text(encoding='utf-8')) if DEPLOYMENTS.exists() else {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def container_state(name):
    if not name:
        return {'status':'missing','health':'none','running':False}
    try:
        proc = docker_cmd(['inspect', name], timeout=8)
        if proc.returncode != 0:
            return {'status':'missing','health':'none','running':False}
        data = json.loads(proc.stdout)[0]
        state = data.get('State') or {}
        return {
            'status': state.get('Status') or 'unknown',
            'health': ((state.get('Health') or {}).get('Status') or 'none'),
            'running': bool(state.get('Running')),
            'started_at': state.get('StartedAt') or '',
            'restart_count': int(data.get('RestartCount') or 0),
        }
    except Exception as exc:
        return {'status':'error','health':'none','running':False,'error':str(exc)}


def public_http_status(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'NOVEC-Monitor/1.0'}, method='GET')
        with urllib.request.urlopen(req, timeout=4) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return 0


def resolve_addresses(hostname):
    try:
        return sorted({x[4][0] for x in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)})[:6]
    except Exception:
        return []


def volume_rows():
    rows = []
    try:
        proc = docker_cmd(['volume','ls','--format','{{json .}}'], timeout=12)
        if proc.returncode != 0:
            return rows
        for line in proc.stdout.splitlines():
            try:
                raw = json.loads(line)
            except Exception:
                continue
            name = str(raw.get('Name') or '').strip()
            if not name:
                continue
            attached = []
            try:
                p = docker_cmd(['ps','-a','--filter',f'volume={name}','--format','{{.Names}}'], timeout=8)
                attached = [x.strip() for x in p.stdout.splitlines() if x.strip()]
            except Exception:
                pass
            rows.append({
                'name': name,
                'driver': raw.get('Driver') or 'local',
                'scope': raw.get('Scope') or 'local',
                'size': raw.get('Size') or '',
                'attached_to': attached,
                'orphan': not bool(attached),
            })
    except Exception:
        pass
    rows.sort(key=lambda x: (not x['orphan'], x['name'].lower()))
    return rows


def backup_rows():
    BACKUPS.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(BACKUPS.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(row, dict):
                row['metadata_file'] = path.name
                rows.append(row)
        except Exception:
            pass
    return rows[:200]


def admin_snapshot():
    registry = load_registry()
    domains = []
    monitoring = []
    for hostname, item in sorted(registry.items()):
        if not isinstance(item, dict):
            continue
        container = str(item.get('container') or '')
        state = container_state(container)
        url = item.get('url') or f'https://{hostname}'
        http_status = public_http_status(url)
        dns = resolve_addresses(hostname)
        base = {
            'hostname': hostname,
            'url': url,
            'app_id': item.get('app_id') or '',
            'name': item.get('name') or item.get('app_id') or hostname,
            'container': container,
            'port': item.get('port'),
            'image': item.get('image') or '',
            'dns': dns,
            'dns_ok': bool(dns),
            'http_status': http_status,
            'http_ok': 200 <= http_status < 500,
            'created_at': item.get('created_at'),
        }
        domains.append(dict(base))
        monitoring.append({**base, **state})

    disk = shutil.disk_usage(Path.home())
    docker_version = ''
    try:
        p = docker_cmd(['version','--format','{{.Server.Version}}'], timeout=8)
        docker_version = p.stdout.strip() if p.returncode == 0 else ''
    except Exception:
        pass
    return {
        'ok': True,
        'generated_at': int(time.time()),
        'domains': domains,
        'volumes': volume_rows(),
        'backups': backup_rows(),
        'monitoring': monitoring,
        'system': {
            'docker_ok': bool(docker_version),
            'docker_version': docker_version,
            'disk_total': disk.total,
            'disk_used': disk.used,
            'disk_free': disk.free,
            'deployments': len(domains),
        },
    }


def run_deploy_job(job):
    with LOCK:
        job['status'] = 'running'
        job['started_at'] = int(time.time())
        job['updated_at'] = int(time.time())
        save_job(job)
    append_log(job, f"NOVEC deploy job {job['id']} started")
    append_log(job, f"App: {job['app_id']}  Host: {job['subdomain']}.novec.online")
    cmd = [sys.executable, str(HELPER), job['app_id'], job['subdomain'], job['template_key']]
    try:
        proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
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
    except Exception as exc:
        rc = -1
        last_json = {'ok': False, 'error': str(exc)}
        append_log(job, f"ERROR: {exc}")
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


def run_backup_job(job):
    with LOCK:
        job['status'] = 'running'
        job['started_at'] = int(time.time())
        save_job(job)
    hostname = job['hostname']
    registry = load_registry()
    item = registry.get(hostname) or {}
    container = str(item.get('container') or '')
    append_log(job, f'Backup started for {hostname}')
    try:
        if not container:
            raise RuntimeError('DEPLOYMENT_NOT_FOUND')
        inspect = docker_cmd(['inspect', container], timeout=12)
        if inspect.returncode != 0:
            raise RuntimeError('CONTAINER_NOT_FOUND')
        data = json.loads(inspect.stdout)[0]
        mounts = [m for m in (data.get('Mounts') or []) if m.get('Type') == 'volume' and m.get('Name')]
        BACKUPS.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        safe_host = re.sub(r'[^a-z0-9.-]+','-',hostname.lower())
        files = []
        if mounts:
            docker = docker_bin()
            if not docker:
                raise RuntimeError('DOCKER_NOT_FOUND')
            subprocess.run([docker,'pull','alpine:3.20'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=180, check=False)
            for index, mount in enumerate(mounts, start=1):
                volume = mount['Name']
                filename = f'{safe_host}__{index}__{stamp}.tar.gz'
                append_log(job, f'[{index}/{len(mounts)}] Archiving volume {volume}…')
                proc = subprocess.run([
                    docker,'run','--rm',
                    '-v',f'{volume}:/src:ro',
                    '-v',f'{BACKUPS}:/backup',
                    'alpine:3.20','tar','-czf',f'/backup/{filename}','-C','/src','.'
                ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=1800)
                if proc.returncode != 0:
                    raise RuntimeError('BACKUP_FAILED: ' + proc.stdout[-1000:])
                path = BACKUPS / filename
                files.append({'file':filename,'volume':volume,'bytes':path.stat().st_size if path.exists() else 0})
        metadata = {
            'id': job['id'],
            'hostname': hostname,
            'app_id': item.get('app_id') or '',
            'container': container,
            'created_at': int(time.time()),
            'files': files,
            'volume_count': len(mounts),
            'bytes': sum(int(x.get('bytes') or 0) for x in files),
            'status': 'success',
        }
        (BACKUPS / f'{safe_host}__{stamp}.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        append_log(job, f'Backup complete: {len(files)} volume archive(s).')
        with LOCK:
            job['status'] = 'success'
            job['result'] = metadata
            job['error'] = None
    except Exception as exc:
        append_log(job, f'Backup failed: {exc}')
        with LOCK:
            job['status'] = 'error'
            job['error'] = str(exc)
            job['result'] = None
    with LOCK:
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

    def read_payload(self):
        length = min(int(self.headers.get('Content-Length','0')), 16384)
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json(200, {"ok": True, "mode": "async"})
            return
        if path.startswith('/job/'):
            if not self.authorized():
                self.send_json(403, {"ok": False, "error": "FORBIDDEN"})
                return
            job = load_job(path.rsplit('/', 1)[-1])
            if not job:
                self.send_json(404, {"ok": False, "error": "JOB_NOT_FOUND"})
                return
            self.send_json(200, job)
            return
        if path == '/admin/snapshot':
            if not self.authorized():
                self.send_json(403, {'ok':False,'error':'FORBIDDEN'})
                return
            try:
                self.send_json(200, admin_snapshot())
            except Exception as exc:
                self.send_json(500, {'ok':False,'error':str(exc)})
            return
        self.send_json(404, {"ok": False, "error": "NOT_FOUND"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.authorized():
            self.send_json(403, {"ok": False, "error": "FORBIDDEN"})
            return
        try:
            payload = self.read_payload()
        except Exception:
            self.send_json(400, {'ok':False,'error':'INVALID_JSON'})
            return

        if path == '/deploy':
            try:
                app_id = str(payload.get('app_id','')).strip().lower()
                subdomain = str(payload.get('subdomain','')).strip().lower()
                template_key = str(payload.get('template_key',app_id)).strip().lower()
                if not app_id or not subdomain or not template_key:
                    raise ValueError('missing fields')
            except Exception:
                self.send_json(400, {'ok':False,'error':'INVALID_JSON'})
                return
            job_id = uuid.uuid4().hex[:16]
            now = int(time.time())
            job = {'id':job_id,'action':'deploy','app_id':app_id,'subdomain':subdomain,'template_key':template_key,'status':'queued','created_at':now,'updated_at':now,'started_at':None,'finished_at':None,'result':None,'error':None,'log':['Deployment queued.']}
            save_job(job)
            threading.Thread(target=run_deploy_job,args=(job,),daemon=True).start()
            self.send_json(202, {'ok':True,'job_id':job_id,'status':'queued'})
            return

        if path == '/admin/restart':
            hostname = str(payload.get('hostname') or '').strip().lower()
            item = load_registry().get(hostname) or {}
            container = str(item.get('container') or '')
            if not container:
                self.send_json(404, {'ok':False,'error':'DEPLOYMENT_NOT_FOUND'})
                return
            try:
                proc = docker_cmd(['restart',container], timeout=60)
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.strip() or 'RESTART_FAILED')
                self.send_json(200, {'ok':True,'hostname':hostname,'container':container})
            except Exception as exc:
                self.send_json(500, {'ok':False,'error':str(exc)})
            return

        if path == '/admin/delete-volume':
            name = str(payload.get('name') or '').strip()
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', name):
                self.send_json(400, {'ok':False,'error':'INVALID_VOLUME'})
                return
            try:
                attached = docker_cmd(['ps','-a','--filter',f'volume={name}','--format','{{.Names}}'], timeout=8).stdout.strip()
                if attached:
                    self.send_json(409, {'ok':False,'error':'VOLUME_IN_USE'})
                    return
                proc = docker_cmd(['volume','rm',name], timeout=30)
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.strip() or 'VOLUME_DELETE_FAILED')
                self.send_json(200, {'ok':True,'name':name})
            except Exception as exc:
                self.send_json(500, {'ok':False,'error':str(exc)})
            return

        if path == '/admin/backup':
            hostname = str(payload.get('hostname') or '').strip().lower()
            if hostname not in load_registry():
                self.send_json(404, {'ok':False,'error':'DEPLOYMENT_NOT_FOUND'})
                return
            job_id = uuid.uuid4().hex[:16]
            now = int(time.time())
            job = {'id':job_id,'action':'backup','hostname':hostname,'status':'queued','created_at':now,'updated_at':now,'started_at':None,'finished_at':None,'result':None,'error':None,'log':['Backup queued.']}
            save_job(job)
            threading.Thread(target=run_backup_job,args=(job,),daemon=True).start()
            self.send_json(202, {'ok':True,'job_id':job_id,'status':'queued'})
            return

        self.send_json(404, {"ok": False, "error": "NOT_FOUND"})


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    JOBS.mkdir(parents=True, exist_ok=True)
    BACKUPS.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NOVEC deploy agent listening on {HOST}:{PORT} (async jobs + management)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
