import json
import urllib.request
from typing import Optional

from fastapi import Header, HTTPException

from app import (
    api,
    DATA,
    ICONS,
    ONE_CLICK_APPS,
    AGENT_SECRET_FILE,
    DEPLOYMENTS,
    DeployRequest,
    app_by_id,
    load_catalog,
    require_admin,
)

AGENT_URL = 'http://host.docker.internal:18791'


def remove_route(path, methods=None):
    keep = []
    wanted = set(methods or [])
    for route in api.router.routes:
        route_methods = set(getattr(route, 'methods', set()) or set())
        if getattr(route, 'path', None) == path and (not wanted or route_methods.intersection(wanted)):
            continue
        keep.append(route)
    api.router.routes = keep


def agent_request(path, payload=None, timeout=310):
    headers = {'User-Agent': 'NOVEC-App-Store/0.3'}
    data = None
    if payload is not None:
        secret = AGENT_SECRET_FILE.read_text(encoding='utf-8').strip() if AGENT_SECRET_FILE.exists() else ''
        if not secret:
            raise HTTPException(status_code=503, detail='Deploy agent secret missing')
        headers['X-NOVEC-Agent-Secret'] = secret
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(AGENT_URL + path, data=data, headers=headers, method='POST' if payload is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode('utf-8'))
            return r.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode('utf-8'))
        except Exception:
            body = {'ok': False, 'error': str(e)}
        return e.code, body
    except Exception as e:
        raise HTTPException(status_code=503, detail=f'Deploy agent unavailable: {e}')


remove_route('/api/deploy', {'POST'})
remove_route('/api/deployments', {'GET'})
remove_route('/api/health', {'GET'})


@api.post('/api/deploy')
def deploy_v2(req: DeployRequest, x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    app = app_by_id(req.app_id)
    if not app:
        raise HTTPException(status_code=404, detail='App not found')
    if req.app_id not in ONE_CLICK_APPS:
        raise HTTPException(status_code=400, detail='This app does not have a reviewed one-click template yet')
    sub = req.subdomain.strip().lower()
    import re
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', sub):
        raise HTTPException(status_code=400, detail='Invalid subdomain')
    if sub in {'store','n8n','www','api','dev','ssh','mail'}:
        raise HTTPException(status_code=400, detail='Reserved subdomain')
    status, body = agent_request('/deploy', {'app_id': req.app_id, 'subdomain': sub})
    if status >= 400 or not body.get('ok'):
        raise HTTPException(status_code=400 if status < 500 else 502, detail=body.get('error', 'Deployment failed'))
    return body


@api.get('/api/deployments')
def deployments_v2(x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    if not DEPLOYMENTS.exists():
        return {'deployments': {}}
    try:
        return {'deployments': json.loads(DEPLOYMENTS.read_text(encoding='utf-8'))}
    except Exception:
        return {'deployments': {}}


@api.get('/api/health')
def health_v2():
    cat = load_catalog()
    cached = len([p for p in ICONS.glob('*') if p.suffix != '.miss']) if ICONS.exists() else 0
    agent_ok = False
    try:
        _, result = agent_request('/health', timeout=2)
        agent_ok = bool(result.get('ok'))
    except Exception:
        agent_ok = False
    return {
        'ok': True,
        'apps': cat['count'],
        'cached_icons': cached,
        'icon_source': 'dashboard-icons+website',
        'deploy_agent': agent_ok,
        'one_click_templates': len(ONE_CLICK_APPS),
    }
