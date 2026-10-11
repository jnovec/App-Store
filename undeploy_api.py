import json
import re
import urllib.error
import urllib.request
from typing import Optional

from fastapi import Header, HTTPException
from pydantic import BaseModel

from app import AGENT_SECRET_FILE, DEPLOYMENTS, api, require_admin

UNDEPLOY_AGENT_URL = 'http://host.docker.internal:18792'
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


def undeploy_agent_request(path, payload=None, timeout=6):
    secret = AGENT_SECRET_FILE.read_text(encoding='utf-8').strip() if AGENT_SECRET_FILE.exists() else ''
    if not secret:
        raise HTTPException(status_code=503, detail='Undeploy agent secret missing')
    headers = {
        'User-Agent': 'NOVEC-App-Store/0.7',
        'X-NOVEC-Agent-Secret': secret,
    }
    data = None
    method = 'GET'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
        method = 'POST'
    request = urllib.request.Request(UNDEPLOY_AGENT_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode('utf-8'))
        except Exception:
            body = {'ok': False, 'error': str(exc)}
        return exc.code, body
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f'Undeploy agent unavailable: {exc}')


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

    status, body = undeploy_agent_request('/undeploy', {
        'hostname': hostname,
        'purge_data': bool(req.purge_data),
    }, timeout=5)
    if status >= 400 or not body.get('ok'):
        raise HTTPException(status_code=400 if status < 500 else 502, detail=body.get('error', 'Removal could not start'))
    return {
        'ok': True,
        'removal_id': body.get('job_id'),
        'status': body.get('status', 'queued'),
        'hostname': hostname,
        'purge_data': bool(req.purge_data),
    }


@api.get('/api/undeploy-status/{job_id}')
def undeploy_status(job_id: str, x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    if not re.fullmatch(r'[a-f0-9]{8,64}', job_id):
        raise HTTPException(status_code=400, detail='Invalid removal id')
    status, body = undeploy_agent_request('/job/' + job_id, timeout=4)
    if status == 404:
        raise HTTPException(status_code=404, detail='Removal job not found')
    if status >= 400:
        raise HTTPException(status_code=502, detail=body.get('error', 'Undeploy agent error'))
    return body
