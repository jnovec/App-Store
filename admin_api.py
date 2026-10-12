import json
import secrets
import time
from typing import Optional

from fastapi import Header, HTTPException
from pydantic import BaseModel

from app import api, ADMIN_PIN_FILE, DATA, ICONS, load_catalog, require_admin, sync_catalog
from server import agent_request, enriched_catalog
from template_catalog import load_templates


class HostRequest(BaseModel):
    hostname: str


class BackupRequest(BaseModel):
    hostname: str


class VolumeRequest(BaseModel):
    name: str


def _admin(pin):
    require_admin(pin)


@api.get('/api/admin/snapshot')
def admin_snapshot(x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    status, body = agent_request('/admin/snapshot', timeout=15, auth=True)
    if status >= 400 or not body.get('ok'):
        raise HTTPException(status_code=502, detail=body.get('error', 'Management agent error'))
    return body


@api.post('/api/admin/restart')
def admin_restart(req: HostRequest, x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    status, body = agent_request('/admin/restart', {'hostname': req.hostname}, timeout=20, auth=True)
    if status >= 400 or not body.get('ok'):
        raise HTTPException(status_code=400 if status < 500 else 502, detail=body.get('error', 'Restart failed'))
    return body


@api.post('/api/admin/backup', status_code=202)
def admin_backup(req: BackupRequest, x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    status, body = agent_request('/admin/backup', {'hostname': req.hostname}, timeout=5, auth=True)
    if status >= 400 or not body.get('ok'):
        raise HTTPException(status_code=400 if status < 500 else 502, detail=body.get('error', 'Backup could not start'))
    return body


@api.post('/api/admin/delete-volume')
def admin_delete_volume(req: VolumeRequest, x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    status, body = agent_request('/admin/delete-volume', {'name': req.name}, timeout=20, auth=True)
    if status >= 400 or not body.get('ok'):
        raise HTTPException(status_code=400 if status < 500 else 502, detail=body.get('error', 'Volume removal failed'))
    return body


@api.get('/api/admin/job/{job_id}')
def admin_job(job_id: str, x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    status, body = agent_request('/job/' + job_id, timeout=5, auth=True)
    if status == 404:
        raise HTTPException(status_code=404, detail='Job not found')
    if status >= 400:
        raise HTTPException(status_code=502, detail=body.get('error', 'Agent error'))
    return body


@api.get('/api/admin/catalog')
def admin_catalog(x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    cat, apps, templates, one_click = enriched_catalog()
    cache = DATA / 'portainer-templates.json'
    return {
        'ok': True,
        'synced_at': cat.get('synced_at'),
        'awesome_selfhosted': cat.get('count', 0),
        'total_apps': len(apps),
        'one_click': one_click,
        'safe_templates': len(templates),
        'cached_icons': len([p for p in ICONS.glob('*') if p.is_file() and p.suffix != '.miss']) if ICONS.exists() else 0,
        'portainer_cache_updated': int(cache.stat().st_mtime) if cache.exists() else None,
        'sources': [
            {'name':'Awesome Selfhosted','type':'catalog','status':'connected'},
            {'name':'Portainer Templates','type':'deploy templates','status':'connected'},
            {'name':'Dashboard Icons','type':'icons','status':'connected'},
        ],
    }


@api.post('/api/admin/catalog-sync')
def admin_catalog_sync(x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    data = sync_catalog()
    templates = load_templates(DATA, force=True)
    return {
        'ok': True,
        'awesome_selfhosted': data.get('count', 0),
        'synced_at': data.get('synced_at'),
        'safe_templates': len(templates),
    }


@api.post('/api/admin/rotate-pin')
def admin_rotate_pin(x_novec_admin_pin: Optional[str] = Header(default=None)):
    _admin(x_novec_admin_pin)
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    pin = ''.join(secrets.choice(alphabet) for _ in range(10))
    ADMIN_PIN_FILE.write_text(pin, encoding='utf-8')
    return {'ok': True, 'pin': pin, 'rotated_at': int(time.time())}
