import os, json, subprocess, threading, time, re, urllib.request, urllib.parse, mimetypes
from pathlib import Path
from typing import Optional
import yaml
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE = Path('/app')
DATA = Path('/data')
REPO = DATA / 'awesome-selfhosted-data'
CATALOG = DATA / 'catalog.json'
ICONS = DATA / 'icons'
ICON_CACHE_VERSION = DATA / 'icon-cache-version.txt'
ICON_CACHE_VERSION_VALUE = 'dashboard-icons-v4'
DASHBOARD_TREE = DATA / 'dashboard-icons-tree.json'
DASHBOARD_TREE_URL = 'https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/tree.json'
DASHBOARD_CDN = 'https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png'

api = FastAPI(title='NOVEC App Store', version='0.2.4')
_dashboard_icon_names = None

def ensure_icon_cache_version():
    ICONS.mkdir(parents=True, exist_ok=True)
    current = ICON_CACHE_VERSION.read_text(encoding='utf-8').strip() if ICON_CACHE_VERSION.exists() else ''
    if current != ICON_CACHE_VERSION_VALUE:
        for p in ICONS.iterdir():
            if p.is_file():
                try: p.unlink()
                except Exception: pass
        ICON_CACHE_VERSION.write_text(ICON_CACHE_VERSION_VALUE, encoding='utf-8')

def slugify(value: str):
    value = (value or '').lower().strip()
    value = value.replace('&', ' and ')
    value = re.sub(r'[^a-z0-9]+', '-', value)
    return value.strip('-')

def dashboard_icon_names():
    global _dashboard_icon_names
    if _dashboard_icon_names is not None:
        return _dashboard_icon_names
    try:
        stale = not DASHBOARD_TREE.exists() or (time.time() - DASHBOARD_TREE.stat().st_mtime > 86400)
        if stale:
            req = urllib.request.Request(DASHBOARD_TREE_URL, headers={'User-Agent':'NOVEC-App-Store/1.0'})
            with urllib.request.urlopen(req, timeout=10) as r:
                DASHBOARD_TREE.write_bytes(r.read(2 * 1024 * 1024))
        data = json.loads(DASHBOARD_TREE.read_text(encoding='utf-8'))
        _dashboard_icon_names = {Path(x).stem for x in data.get('png', []) if not Path(x).stem.endswith(('-light','-dark'))}
    except Exception as e:
        print('dashboard icon index failed:', e, flush=True)
        _dashboard_icon_names = set()
    return _dashboard_icon_names

def icon_candidates(app):
    vals = [app.get('id',''), app.get('name','')]
    source = app.get('source') or ''
    m = re.match(r'https?://github\.com/[^/]+/([^/#?]+)', source)
    if m:
        vals.append(m.group(1).removesuffix('.git'))
    out = []
    for v in vals:
        s = slugify(v)
        if s and s not in out:
            out.append(s)
    return out

def sync_catalog():
    DATA.mkdir(parents=True, exist_ok=True)
    ensure_icon_cache_version()
    dashboard_icon_names()
    if not REPO.exists():
        subprocess.run(['git','clone','--depth','1','https://github.com/awesome-selfhosted/awesome-selfhosted-data.git',str(REPO)], check=True)
    else:
        subprocess.run(['git','-C',str(REPO),'fetch','--depth','1','origin','master'], check=True)
        subprocess.run(['git','-C',str(REPO),'reset','--hard','origin/master'], check=True)

    apps = []
    for f in sorted((REPO/'software').glob('*.yml')):
        try:
            d = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
            name = d.get('name') or f.stem
            tags = d.get('tags') or []
            platforms = d.get('platforms') or []
            release = d.get('current_release') or {}
            archived = bool(d.get('archived', False))
            dockerish = any(str(x).lower() in ('docker','docker compose') for x in platforms)
            apps.append({
                'id': f.stem,
                'name': name,
                'description': d.get('description') or '',
                'tags': tags,
                'platforms': platforms,
                'source': d.get('source_code_url') or '',
                'website': d.get('website_url') or '',
                'stars': d.get('stargazers_count') or 0,
                'updated': str(d.get('updated_at') or ''),
                'version': release.get('tag') if isinstance(release, dict) else '',
                'archived': archived,
                'ready': dockerish and not archived,
                'initials': ''.join([p[0] for p in re.split(r'[\s\-_]+', name) if p])[:2].upper(),
                'icon': f'/api/icon/{urllib.parse.quote(f.stem, safe="")}?v=4'
            })
        except Exception:
            pass
    payload = {'synced_at': time.time(), 'count': len(apps), 'apps': apps}
    CATALOG.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return payload

def load_catalog():
    if not CATALOG.exists(): return sync_catalog()
    return json.loads(CATALOG.read_text(encoding='utf-8'))

def background_sync():
    while True:
        try: sync_catalog()
        except Exception as e: print('sync failed:', e, flush=True)
        time.sleep(21600)

def safe_icon_id(app_id: str):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', app_id)[:180]

def app_by_id(app_id: str):
    for app in load_catalog()['apps']:
        if app['id'] == app_id: return app
    return None

def cached_icon(app_id: str):
    sid = safe_icon_id(app_id)
    for ext in ('png','jpg','jpeg','ico','webp','svg'):
        p = ICONS / f'{sid}.{ext}'
        if p.exists() and p.stat().st_size > 64: return p
    return None

def miss_path(app_id: str):
    return ICONS / f'{safe_icon_id(app_id)}.miss'

def download_icon(url: str, target_base: Path):
    if not url or not url.startswith(('http://','https://')): return None
    req = urllib.request.Request(url, headers={'User-Agent':'NOVEC-App-Store/1.0','Accept':'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            ctype = (r.headers.get('Content-Type') or '').split(';')[0].lower()
            data = r.read(1024 * 1024)
            if len(data) < 64 or (ctype and not ctype.startswith('image/')): return None
            ext = mimetypes.guess_extension(ctype) or Path(urllib.parse.urlparse(url).path).suffix or '.png'
            ext = ext.lower()
            if ext == '.jpe': ext = '.jpg'
            if ext not in ('.png','.jpg','.jpeg','.ico','.webp','.svg'): ext = '.png'
            out = Path(str(target_base) + ext)
            out.write_bytes(data)
            return out
    except Exception:
        return None

def resolve_icon(app):
    ensure_icon_cache_version()
    existing = cached_icon(app['id'])
    if existing: return existing
    miss = miss_path(app['id'])
    if miss.exists(): return None
    base = ICONS / safe_icon_id(app['id'])

    known = dashboard_icon_names()
    for slug in icon_candidates(app):
        if slug in known:
            got = download_icon(f'{DASHBOARD_CDN}/{slug}.png', base)
            if got: return got

    website = app.get('website') or ''
    if website:
        try:
            parsed = urllib.parse.urlparse(website)
            host = (parsed.hostname or '').lower()
            if host and host != 'github.com' and not host.endswith('.github.com'):
                root = f'{parsed.scheme}://{parsed.netloc}'
                for path in ('/apple-touch-icon.png','/favicon.png','/favicon.ico'):
                    got = download_icon(root + path, base)
                    if got: return got
        except Exception:
            pass

    source = app.get('source') or ''
    m = re.match(r'https?://github\.com/([^/]+)/([^/#?]+)', source)
    if m:
        owner, repo = m.group(1), m.group(2).removesuffix('.git')
        for branch in ('main','master'):
            raw = f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/app.json'
            try:
                req = urllib.request.Request(raw, headers={'User-Agent':'NOVEC-App-Store/1.0'})
                with urllib.request.urlopen(req, timeout=4) as r:
                    d = json.loads(r.read(512 * 1024).decode('utf-8'))
                logo = d.get('logo') if isinstance(d, dict) else None
                got = download_icon(logo, base) if logo else None
                if got: return got
            except Exception:
                pass

    try: miss.write_text(str(time.time()), encoding='utf-8')
    except Exception: pass
    return None

@api.on_event('startup')
def startup():
    ensure_icon_cache_version()
    try: sync_catalog()
    except Exception as e: print('initial sync failed:', e, flush=True)
    threading.Thread(target=background_sync, daemon=True).start()

@api.get('/api/apps')
def apps(q: str = '', tag: str = '', ready: Optional[bool] = None, limit: int = Query(120, ge=1, le=2000)):
    cat = load_catalog(); rows = cat['apps']
    if q:
        needle = q.lower(); rows = [a for a in rows if needle in (a['name']+' '+a['description']+' '+' '.join(a['tags'])).lower()]
    if tag: rows = [a for a in rows if tag.lower() in [str(t).lower() for t in a['tags']]]
    if ready is not None: rows = [a for a in rows if a['ready'] == ready]
    rows = sorted(rows, key=lambda a: (a['archived'], -int(a['stars'] or 0), a['name'].lower()))
    ready_count = sum(1 for a in cat['apps'] if a['ready'])
    active_count = sum(1 for a in cat['apps'] if not a['archived'])
    tags = {}
    for a in cat['apps']:
        for t in a['tags']: tags[t] = tags.get(t, 0) + 1
    return {'synced_at':cat['synced_at'],'stats':{'total':cat['count'],'active':active_count,'ready':ready_count},'top_tags':sorted(tags.items(), key=lambda x:-x[1])[:40],'apps':rows[:limit]}

@api.get('/api/icon/{app_id}')
def icon(app_id: str):
    app = app_by_id(app_id)
    if not app: raise HTTPException(status_code=404, detail='App not found')
    path = resolve_icon(app)
    if not path: raise HTTPException(status_code=404, detail='Icon not available')
    return FileResponse(path, headers={'Cache-Control':'public, max-age=604800, immutable'})

@api.post('/api/sync')
def sync():
    data = sync_catalog(); return {'ok':True,'count':data['count'],'synced_at':data['synced_at']}

@api.get('/api/health')
def health():
    cat = load_catalog(); cached = len([p for p in ICONS.glob('*') if p.suffix != '.miss']) if ICONS.exists() else 0
    return {'ok':True,'apps':cat['count'],'cached_icons':cached,'icon_source':'dashboard-icons+website'}

@api.get('/')
def root():
    html = (BASE/'static'/'index.html').read_text(encoding='utf-8')
    html = html.replace('</head>', '<link rel="stylesheet" href="/static/icon-enhancer.css"></head>')
    html = html.replace('</body>', '<script src="/static/icon-enhancer.js"></script></body>')
    return HTMLResponse(html)

api.mount('/static', StaticFiles(directory=BASE/'static'), name='static')
