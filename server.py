import json
import re
import urllib.request
from typing import Optional

from fastapi import Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from app import (
    api,
    BASE,
    DATA,
    ICONS,
    AGENT_SECRET_FILE,
    DEPLOYMENTS,
    DeployRequest,
    load_catalog,
    require_admin,
)
from template_catalog import load_templates, match_app, slugify

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
    headers = {'User-Agent': 'NOVEC-App-Store/0.6'}
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
    matched = set()

    for original in cat['apps']:
        app = dict(original)
        key, tpl = match_app(app, templates)
        app['one_click'] = bool(tpl)
        app['template_key'] = key or ''
        app['deploy_image'] = tpl.get('image') if tpl else ''
        app['deploy_source'] = tpl.get('source') if tpl else ''
        if key:
            matched.add(key)
        apps.append(app)

    for key, tpl in templates.items():
        if key in matched:
            continue
        name = tpl.get('title') or tpl.get('name') or key
        categories = tpl.get('categories') or ['Docker']
        apps.append({
            'id': 'pt-' + key,
            'name': name,
            'description': tpl.get('description') or ('Deployable Docker application: ' + name),
            'tags': categories,
            'platforms': ['Docker'],
            'source': '',
            'website': '',
            'stars': 0,
            'updated': '',
            'version': '',
            'archived': False,
            'ready': True,
            'initials': ''.join([p[0] for p in re.split(r'[\s\-_]+', name) if p])[:2].upper(),
            'icon': '',
            'one_click': True,
            'template_key': key,
            'deploy_image': tpl.get('image') or '',
            'deploy_source': tpl.get('source') or 'portainer',
            'catalog_source': 'Portainer templates',
        })

    one_click = sum(1 for a in apps if a.get('one_click'))
    return cat, apps, templates, one_click


def find_enriched_app(app_id):
    _, apps, templates, _ = enriched_catalog()
    for app in apps:
        if app.get('id') == app_id:
            key = app.get('template_key') or ''
            return app, key, templates.get(key) if key else None
    return None, '', None


remove_route('/api/apps', {'GET'})
remove_route('/api/deploy', {'POST'})
remove_route('/api/deploy-status/{job_id}', {'GET'})
remove_route('/api/deployments', {'GET'})
remove_route('/api/health', {'GET'})
remove_route('/', {'GET'})


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
    active_count = sum(1 for a in rows if not a.get('archived')) if (q or tag or ready is not None) else sum(1 for a in enriched_catalog()[1] if not a.get('archived'))
    all_apps = enriched_catalog()[1]
    ready_count = sum(1 for a in all_apps if a.get('ready'))
    tags = {}
    for a in all_apps:
        for t in a.get('tags') or []:
            tags[t] = tags.get(t, 0) + 1
    return {
        'synced_at': cat['synced_at'],
        'stats': {
            'total': len(all_apps),
            'active': sum(1 for a in all_apps if not a.get('archived')),
            'ready': ready_count,
            'one_click': one_click_count,
            'safe_templates': len(templates),
            'awesome_selfhosted': cat['count'],
        },
        'top_tags': sorted(tags.items(), key=lambda x: -x[1])[:40],
        'apps': rows[:limit],
    }


@api.post('/api/deploy', status_code=202)
def deploy_v4(req: DeployRequest, x_novec_admin_pin: Optional[str] = Header(default=None)):
    require_admin(x_novec_admin_pin)
    app, template_key, tpl = find_enriched_app(req.app_id)
    if not app:
        raise HTTPException(status_code=404, detail='App not found')
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
    cat, apps, templates, one_click_count = enriched_catalog()
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
        'apps': len(apps),
        'awesome_selfhosted_apps': cat['count'],
        'cached_icons': cached,
        'icon_source': 'dashboard-icons+website',
        'deploy_agent': agent_ok,
        'deploy_agent_mode': agent_mode,
        'one_click_apps': one_click_count,
        'safe_templates': len(templates),
        'async_deploy': True,
        'deploy_ui': 'floating-terminal',
    }


@api.get('/')
def root_v2():
    html = (BASE/'static'/'index.html').read_text(encoding='utf-8')
    html = html.replace('</head>', '<link rel="stylesheet" href="/static/icon-enhancer.css"><link rel="stylesheet" href="/static/deploy-enhancer.css"><link rel="stylesheet" href="/static/deploy-console.css?v=2"></head>')
    html = html.replace('</body>', '<script src="/static/icon-enhancer.js"></script><script src="/static/deploy-enhancer.js"></script><script src="/static/deploy-console.js?v=2"></script></body>')
    return HTMLResponse(html)
