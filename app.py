import os, json, subprocess, threading, time, re
from pathlib import Path
from typing import Optional
import yaml
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path('/app')
DATA = Path('/data')
REPO = DATA / 'awesome-selfhosted-data'
CATALOG = DATA / 'catalog.json'

api = FastAPI(title='NOVEC App Store', version='0.1.0')

def sync_catalog():
    DATA.mkdir(parents=True, exist_ok=True)
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
                'initials': ''.join([p[0] for p in re.split(r'[\s\-_]+', name) if p])[:2].upper()
            })
        except Exception:
            pass
    payload = {'synced_at': time.time(), 'count': len(apps), 'apps': apps}
    CATALOG.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return payload

def load_catalog():
    if not CATALOG.exists():
        return sync_catalog()
    return json.loads(CATALOG.read_text(encoding='utf-8'))

def background_sync():
    while True:
        try:
            sync_catalog()
        except Exception as e:
            print('sync failed:', e, flush=True)
        time.sleep(21600)

@api.on_event('startup')
def startup():
    try:
        sync_catalog()
    except Exception as e:
        print('initial sync failed:', e, flush=True)
    threading.Thread(target=background_sync, daemon=True).start()

@api.get('/api/apps')
def apps(q: str = '', tag: str = '', ready: Optional[bool] = None, limit: int = Query(120, ge=1, le=2000)):
    cat = load_catalog()
    rows = cat['apps']
    if q:
        needle = q.lower()
        rows = [a for a in rows if needle in (a['name']+' '+a['description']+' '+' '.join(a['tags'])).lower()]
    if tag:
        rows = [a for a in rows if tag.lower() in [str(t).lower() for t in a['tags']]]
    if ready is not None:
        rows = [a for a in rows if a['ready'] == ready]
    rows = sorted(rows, key=lambda a: (a['archived'], -int(a['stars'] or 0), a['name'].lower()))
    ready_count = sum(1 for a in cat['apps'] if a['ready'])
    active_count = sum(1 for a in cat['apps'] if not a['archived'])
    tags = {}
    for a in cat['apps']:
        for t in a['tags']:
            tags[t] = tags.get(t, 0) + 1
    top_tags = sorted(tags.items(), key=lambda x: -x[1])[:40]
    return {
        'synced_at': cat['synced_at'],
        'stats': {'total': cat['count'], 'active': active_count, 'ready': ready_count},
        'top_tags': top_tags,
        'apps': rows[:limit]
    }

@api.post('/api/sync')
def sync():
    data = sync_catalog()
    return {'ok': True, 'count': data['count'], 'synced_at': data['synced_at']}

@api.get('/api/health')
def health():
    cat = load_catalog()
    return {'ok': True, 'apps': cat['count']}

@api.get('/')
def root():
    return FileResponse(BASE/'static'/'index.html')

api.mount('/static', StaticFiles(directory=BASE/'static'), name='static')
