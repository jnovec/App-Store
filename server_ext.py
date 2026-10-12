from fastapi.responses import HTMLResponse

import server
from server import api
import undeploy_api  # noqa: F401
import admin_api  # noqa: F401

api.router.routes = [
    route for route in api.router.routes
    if not (getattr(route, 'path', None) == '/' and 'GET' in set(getattr(route, 'methods', set()) or set()))
]


@api.get('/')
def root_ext():
    response = server.root_v2()
    html = response.body.decode('utf-8')
    html = html.replace(
        '</head>',
        '<link rel="stylesheet" href="/static/deploy-modals.css?v=1">'
        '<link rel="stylesheet" href="/static/admin-panels.css?v=1">'
        '<link rel="stylesheet" href="/static/pagination.css?v=1">'
        '</head>'
    )
    html = html.replace(
        '</body>',
        '<script src="/static/status-retry.js?v=1"></script>'
        '<script src="/static/pagination.js?v=1"></script>'
        '<script src="/static/admin-panels.js?v=1"></script>'
        '</body>'
    )
    return HTMLResponse(html)
