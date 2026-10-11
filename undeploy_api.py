import json
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Header, HTTPException
from pydantic import BaseModel

from app import DEPLOYMENTS, api, require_admin

DATA = Path('/data')
UNDEPLOY_JOBS = DATA / 'undeploy-jobs'
RESERVED_HOSTS = {
    'store.novec.online',
    'n8n.novec.online',
    'www.novec.online',
    'api.novec.online',
    'dev.novec.online',
    'ssh.novec.online',
    'mail.novec.online',
}


class UndeployRequest(BaseModel):
    hostname: str
    purge_data: bool = False


def job_path(job_id: str) -> Path:
    return UNDEPLOY_JOBS / f'{job_id}.json'


def write_job(job):
    UNDEPLOY_JOBS.mkdir(parents=True, exist_ok=True)
    path = job_path(job['id'])
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


@api.post('/api/undeploy', status_code=202)
def undeploy(req: UndeployRequest, x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    hostname = req.hostname.strip().lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.novec\.online', hostname):
        raise HTTPException(status_code=400, detail='Invalid hostname')
    if hostname in RESERVED_HOSTS:
        raise HTTPException(status_code=400, detail='Reserved hostname')

    if not DEPLOYMENTS.exists():
        raise HTTPException(status_code=404, detail='Deployment not found')
    try:
        registry = json.loads(DEPLOYMENTS.read_text(encoding='utf-8'))
    except Exception:
        registry = {}
    if hostname not in registry:
        raise HTTPException(status_code=404, detail='Deployment not found')

    now = int(time.time())
    job_id = uuid.uuid4().hex[:16]
    job = {
        'id': job_id,
        'action': 'undeploy',
        'hostname': hostname,
        'purge_data': bool(req.purge_data),
        'status': 'queued',
        'created_at': now,
        'updated_at': now,
        'started_at': None,
        'finished_at': None,
        'result': None,
        'error': None,
        'log': ['Removal queued. Waiting for NOVEC n8n worker…'],
    }
    write_job(job)
    return {
        'ok': True,
        'removal_id': job_id,
        'status': 'queued',
        'hostname': hostname,
        'purge_data': bool(req.purge_data),
    }


@api.get('/api/undeploy-status/{job_id}')
def undeploy_status(job_id: str, x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    if not re.fullmatch(r'[a-f0-9]{8,64}', job_id):
        raise HTTPException(status_code=400, detail='Invalid removal id')
    path = job_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail='Removal job not found')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        raise HTTPException(status_code=500, detail='Removal job is unreadable')
