import json
import re
import time
import urllib.request
from typing import Optional

from fastapi import Header, HTTPException, Query

from app import (
    api,
    DATA,
    ICONS,
    AGENT_SECRET_FILE,
    DEPLOYMENTS,
    DeployRequest,
    app_by_id,
    load_catalog,
    require_admin,
)
from template_catalog import load_templates, match_app

AGENT_URL = 'http://host.docker.internal:18791'
RESERVED = {'store','n8n','www','api','dev','ssh','mail'}


def remove_route(path, methods=None):
    keep = []
    wanted = set(methods or [])
    for route in api.router.routes:
        route_methods = set(getattr(route, 'methods', set()) or set())
        if getattr(route, 'path', None) == path and (not wanted or route_methods.intersection(wanted)):
            continue
        keep.append(route)
    api.router.routes = keep


def agent_request(path, payload=None, timeout=8, auth=True):
    headers = {'User-Agent': 'NOVEC-App-Store/0.5'}
    if auth:
        secret = AGENT_SECRET_FILE.read_text(encoding='utf-8').strip() if AGENT_SECRET_FILE.exists() else ''
        if not secret:
            raise HTTPException(status_code=503, detail='Deploy agent secret missing')
        headers['X-NOVEC-Agent-Secret'] = secret
    data = None
    method = 'GET'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
        method = 'POST'
    req = urllib.request.Request(AGENT_URL + path, data=data, headers=headers, method=method)
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


def enriched_catalog():
    cat = load_catalog()
    templates = load_templates(DATA)
    apps = []
    one_click = 0
    for original in cat['apps']:
        app = dict(original)
        key, tpl = match_app(app, templates)
        app['one_click'] = bool(tpl)
        app['template_key'] = key or ''
        app['deploy_image'] = tpl.get('image') if tpl else ''
        app['deploy_source'] = tpl.get('source') if tpl else ''
        if tpl:
            one_click += 1
        apps.append(app)
    return cat, apps, templates, one_click


remove_route('/api/apps', {'GET'})
remove_route('/api/deploy', {'POST'})
remove_route('/api/deploy-status/{job_id}', {'GET'})
remove_route('/api/deployments', {'GET'})
remove_route('/api/health', {'GET'})


@api.get('/api/apps')
def apps_v2(q: str = '', tag: str = '', ready: Optional[bool] = None, limit: int = Query(120, ge=1, le=2000)):
    cat, rows, templates, one_click_count = enriched_catalog()
    if q:
        needle = q.lower()
        rows = [a for a in rows if needle in (a['name'] + ' ' + a['description'] + ' ' + ' '.join(a['tags'])).lower()]
    if tag:
        rows = [a for a in rows if tag.lower() in [str(t).lower() for t in a['tags']]]
    if ready is not None:
        rows = [a for a in rows if a['ready'] == ready]
    rows = sorted(rows, key=lambda a: (not a.get('one_click', False), a['archived'], -int(a['stars'] or 0), a['name'].lower()))
    active_count = sum(1 for a in cat['apps'] if not a['archived'])
    ready_count = sum(1 for a in cat['apps'] if a['ready'])
    tags = {}
    for a in cat['apps']:
        for t in a['tags']:
            tags[t] = tags.get(t, 0) + 1
    return {
        'synced_at': cat['synced_at'],
        'stats': {
            'total': cat['count'],
            'active': active_count,
            'ready': ready_count,
            'one_click': one_click_count,
            'safe_templates': len(templates),
        },
        'top_tags': sorted(tags.items(), key=lambda x: -x[1])[:40],
        'apps': rows[:limit],
    }


@api.post('/api/deploy', status_code=202)
def deploy_v4(req: DeployRequest, x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    app = app_by_id(req.app_id)
    if not app:
        raise HTTPException(status_code=404, detail='App not found')
    templates = load_templates(DATA)
    template_key, tpl = match_app(app, templates)
    if not tpl or not template_key:
        raise HTTPException(status_code=400, detail='This app does not have a safe one-click template yet')
    sub = req.subdomain.strip().lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', sub):
        raise HTTPException(status_code=400, detail='Invalid subdomain')
    if sub in RESERVED:
        raise HTTPException(status_code=400, detail='Reserved subdomain')
    status, body = agent_request('/deploy', {
        'app_id': req.app_id,
        'subdomain': sub,
        'template_key': template_key,
    }, timeout=5, auth=True)
    if status >= 400 or not body.get('ok'):
        raise HTTPException(status_code=400 if status < 500 else 502, detail=body.get('error', 'Deployment could not start'))
    return {
        'ok': True,
        'deployment_id': body.get('job_id'),
        'status': body.get('status', 'queued'),
        'app_id': req.app_id,
        'subdomain': sub,
        'template_key': template_key,
    }


@api.get('/api/deploy-status/{job_id}')
def deploy_status_v2(job_id: str, x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    if not re.fullmatch(r'[a-f0-9]{8,64}', job_id):
        raise HTTPException(status_code=400, detail='Invalid deployment id')
    status, body = agent_request(f'/job/{job_id}', timeout=4, auth=True)
    if status == 404:
        raise HTTPException(status_code=404, detail='Deployment job not found')
    if status >= 400:
        raise HTTPException(status_code=502, detail=body.get('error', 'Deploy agent error'))
    return body


@api.get('/api/deployments')
def deployments_v3(x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    if not DEPLOYMENTS.exists():
        return {'deployments': []}
    try:
        raw = json.loads(DEPLOYMENTS.read_text(encoding='utf-8'))
    except Exception:
        raw = {}
    rows = []
    for host, item in raw.items():
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row['host'] = host
        row['url'] = row.get('url') or f'https://{host}'
        rows.append(row)
    rows.sort(key=lambda x: int(x.get('created_at') or 0), reverse=True)
    return {'deployments': rows, 'count': len(rows)}


@api.get('/api/health')
def health_v3():
    cat, _, templates, one_click_count = enriched_catalog()
    cached = len([p for p in ICONS.glob('*') if p.suffix != '.miss']) if ICONS.exists() else 0
    agent_ok = False
    agent_mode = ''
    try:
        _, result = agent_request('/health', timeout=2, auth=False)
        agent_ok = bool(result.get('ok'))
        agent_mode = result.get('mode') or ''
    except Exception:
        agent_ok = False
    return {
        'ok': True,
        'apps': cat['count'],
        'cached_icons': cached,
        'icon_source': 'dashboard-icons+website',
        'deploy_agent': agent_ok,
        'deploy_agent_mode': agent_mode,
        'one_click_apps': one_click_count,
        'safe_templates': len(templates),
        'async_deploy': True,
        'deploy_ui': 'floating-terminal',
    }
