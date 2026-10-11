#!/usr/bin/env python3
import json
import re
import time
import urllib.request
from pathlib import Path

PORTAINER_URL = 'https://raw.githubusercontent.com/Lissy93/portainer-templates/main/templates.json'
CACHE_MAX_AGE = 21600

MANUAL = {
    'uptime-kuma': {'image':'louislam/uptime-kuma:2','port':3001,'volumes':['/app/data'],'env':{},'source':'manual'},
    'it-tools': {'image':'corentinth/it-tools:latest','port':80,'volumes':[],'env':{},'source':'manual'},
    'stirling-pdf': {'image':'stirlingtools/stirling-pdf:latest','port':8080,'volumes':['/configs'],'env':{},'source':'manual'},
    'mealie': {'image':'ghcr.io/mealie-recipes/mealie:latest','port':9000,'volumes':['/app/data'],'env':{},'source':'manual'},
    'nocodb': {'image':'nocodb/nocodb:latest','port':8080,'volumes':['/usr/app/data'],'env':{},'source':'manual'},
    'gitea': {'image':'gitea/gitea:latest','port':3000,'volumes':['/data'],'env':{},'source':'manual'},
    'vaultwarden': {'image':'vaultwarden/server:latest','port':80,'volumes':['/data'],'env':{},'source':'manual'},
    'open-webui': {'image':'ghcr.io/open-webui/open-webui:main','port':8080,'volumes':['/app/backend/data'],'env':{},'source':'manual'},
    'metabase': {'image':'metabase/metabase:latest','port':3000,'volumes':[],'env':{},'source':'manual'},
}

PREFERRED_PORTS = [80, 8080, 3000, 8000, 9000, 5000, 8096, 8123, 32400, 8989, 7878, 9696, 5055, 2283, 4533, 8081, 3001, 5001, 8384, 9090]
FORBIDDEN_VOLUME_PARTS = ['/var/run/docker.sock', '/dev/', '/proc/', '/sys/']


def slugify(value):
    value = (value or '').lower().strip().replace('&', ' and ')
    value = re.sub(r'[^a-z0-9]+', '-', value).strip('-')
    return value


def _port_number(value):
    s = str(value or '').split('/')[0]
    last = s.split(':')[-1]
    return int(last) if last.isdigit() else None


def _choose_port(ports):
    nums = [p for p in (_port_number(x) for x in (ports or [])) if p]
    for preferred in PREFERRED_PORTS:
        if preferred in nums:
            return preferred
    return None


def _safe_template(item):
    if int(item.get('type') or 0) != 1:
        return None
    image = str(item.get('image') or '').strip()
    if not image:
        return None
    if item.get('privileged') or item.get('interactive'):
        return None
    network = str(item.get('network_mode') or item.get('network') or '').lower()
    if network == 'host':
        return None
    if item.get('devices') or item.get('cap_add') or item.get('capabilities'):
        return None
    port = _choose_port(item.get('ports'))
    if not port:
        return None

    volumes = []
    for vol in item.get('volumes') or []:
        if not isinstance(vol, dict):
            continue
        container = str(vol.get('container') or '').strip()
        bind = str(vol.get('bind') or '').strip()
        joined = (container + ' ' + bind).lower()
        if any(x in joined for x in FORBIDDEN_VOLUME_PARTS):
            return None
        if container.startswith('/'):
            volumes.append(container)

    env = {}
    for e in item.get('env') or []:
        if not isinstance(e, dict):
            continue
        name = str(e.get('name') or '').strip()
        if not name:
            continue
        if 'default' in e and e.get('default') not in (None, ''):
            env[name] = str(e.get('default'))
        elif e.get('preset') is True and e.get('value') not in (None, ''):
            env[name] = str(e.get('value'))

    title = str(item.get('title') or item.get('name') or '').strip()
    name = str(item.get('name') or title).strip()
    key = slugify(name or title)
    if not key:
        return None
    return {
        'key': key,
        'title': title or name,
        'name': name or title,
        'image': image,
        'port': port,
        'volumes': list(dict.fromkeys(volumes)),
        'env': env,
        'command': item.get('command') or '',
        'restart_policy': item.get('restart_policy') or 'unless-stopped',
        'logo': item.get('logo') or '',
        'categories': item.get('categories') or [],
        'description': item.get('description') or '',
        'source': 'portainer',
    }


def _download(cache_path):
    req = urllib.request.Request(PORTAINER_URL, headers={'User-Agent':'NOVEC-App-Store/1.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(12 * 1024 * 1024)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)


def load_templates(data_dir, force=False):
    data_dir = Path(data_dir)
    cache = data_dir / 'portainer-templates.json'
    stale = (not cache.exists()) or (time.time() - cache.stat().st_mtime > CACHE_MAX_AGE)
    if force or stale:
        try:
            _download(cache)
        except Exception:
            if not cache.exists():
                return dict(MANUAL)
    try:
        raw = json.loads(cache.read_text(encoding='utf-8'))
    except Exception:
        return dict(MANUAL)

    out = dict(MANUAL)
    for item in raw.get('templates', []):
        try:
            tpl = _safe_template(item)
            if tpl and tpl['key'] not in out:
                out[tpl['key']] = tpl
        except Exception:
            pass
    return out


def app_candidates(app):
    vals = [app.get('id',''), app.get('name','')]
    source = str(app.get('source') or '')
    m = re.match(r'https?://github\.com/[^/]+/([^/#?]+)', source)
    if m:
        vals.append(m.group(1).removesuffix('.git'))
    out = []
    for v in vals:
        s = slugify(v)
        if s and s not in out:
            out.append(s)
    return out


def match_app(app, templates):
    for candidate in app_candidates(app):
        if candidate in templates:
            return candidate, templates[candidate]
    return None, None
