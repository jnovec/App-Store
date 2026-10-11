#!/usr/bin/env python3
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

TUNNEL_ID = "76ba2ac9-7bde-4986-bed8-1d1c17710006"
HOME = Path.home()
REGISTRY = HOME / "novec-app-store" / "data" / "deployments.json"
TUNNEL_CONFIG = HOME / ".cloudflared" / "novec-app-store-config.yml"

TEMPLATES = {
    "uptime-kuma": {"image": "louislam/uptime-kuma:2", "port": 3001, "volume": "/app/data"},
    "it-tools": {"image": "corentinth/it-tools:latest", "port": 80, "volume": ""},
    "stirling-pdf": {"image": "stirlingtools/stirling-pdf:latest", "port": 8080, "volume": "/configs"},
    "mealie": {"image": "ghcr.io/mealie-recipes/mealie:latest", "port": 9000, "volume": "/app/data"},
    "nocodb": {"image": "nocodb/nocodb:latest", "port": 8080, "volume": "/usr/app/data"},
    "gitea": {"image": "gitea/gitea:latest", "port": 3000, "volume": "/data"},
    "vaultwarden": {"image": "vaultwarden/server:latest", "port": 80, "volume": "/data"},
    "open-webui": {"image": "ghcr.io/open-webui/open-webui:main", "port": 8080, "volume": "/app/backend/data"},
    "metabase": {"image": "metabase/metabase:latest", "port": 3000, "volume": ""},
}

RESERVED = {"store", "n8n", "www", "api", "dev", "ssh", "mail"}


def fail(message, code=1):
    print(json.dumps({"ok": False, "error": message}))
    raise SystemExit(code)


def executable(name, candidates=()):
    found = shutil.which(name)
    if found:
        return found
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def load_registry():
    if not REGISTRY.exists():
        return {}
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_registry(data):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_tunnel_config(registry):
    cred = HOME / ".cloudflared" / f"{TUNNEL_ID}.json"
    lines = [
        f"tunnel: {TUNNEL_ID}",
        f"credentials-file: {cred}",
        "",
        "ingress:",
        "  - hostname: store.novec.online",
        "    service: http://127.0.0.1:8788",
    ]
    for host, item in sorted(registry.items()):
        lines += [
            f"  - hostname: {host}",
            f"    service: http://127.0.0.1:{int(item['port'])}",
        ]
    lines += ["  - service: http_status:404", ""]
    TUNNEL_CONFIG.write_text("\n".join(lines), encoding="utf-8")


def wait_port(port, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=2):
                return True
        except OSError:
            time.sleep(2)
    return False


def main():
    if len(sys.argv) != 3:
        fail("USAGE: deploy_helper.py <app_id> <subdomain>")

    app_id = sys.argv[1].strip().lower()
    subdomain = sys.argv[2].strip().lower()

    if app_id not in TEMPLATES:
        fail("APP_NOT_ONE_CLICK_READY", 2)
    if not subdomain or len(subdomain) > 63 or subdomain in RESERVED:
        fail("INVALID_OR_RESERVED_SUBDOMAIN", 3)
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in subdomain):
        fail("INVALID_SUBDOMAIN", 3)
    if subdomain.startswith("-") or subdomain.endswith("-"):
        fail("INVALID_SUBDOMAIN", 3)

    docker = executable("docker", ["/Applications/Docker.app/Contents/Resources/bin/docker", "/opt/homebrew/bin/docker"])
    cloudflared = executable("cloudflared", ["/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared"])
    launchctl = executable("launchctl", ["/bin/launchctl"])
    if not docker:
        fail("DOCKER_NOT_FOUND", 4)
    if not cloudflared:
        fail("CLOUDFLARED_NOT_FOUND", 5)

    tpl = TEMPLATES[app_id]
    host = f"{subdomain}.novec.online"
    container = f"novec-{app_id}"
    registry = load_registry()

    inspect = subprocess.run([docker, "inspect", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if inspect.returncode != 0:
        subprocess.run([docker, "pull", tpl["image"]], check=True)
        cmd = [
            docker, "run", "-d",
            "--name", container,
            "--restart", "unless-stopped",
            "-p", f"127.0.0.1::{tpl['port']}",
        ]
        if tpl["volume"]:
            cmd += ["-v", f"{container}-data:{tpl['volume']}"]
        cmd += [tpl["image"]]
        subprocess.run(cmd, check=True)
    else:
        subprocess.run([docker, "start", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    port_out = subprocess.check_output([docker, "port", container, f"{tpl['port']}/tcp"], text=True).strip().splitlines()
    if not port_out:
        fail("HOST_PORT_NOT_FOUND", 6)
    host_port = int(port_out[0].rsplit(":", 1)[1])

    if not wait_port(host_port):
        logs = subprocess.run([docker, "logs", "--tail", "80", container], capture_output=True, text=True)
        print(logs.stdout[-4000:], file=sys.stderr)
        print(logs.stderr[-4000:], file=sys.stderr)
        fail("APP_HEALTH_TIMEOUT", 7)

    if host not in registry:
        route = subprocess.run([cloudflared, "tunnel", "route", "dns", TUNNEL_ID, host], capture_output=True, text=True)
        if route.returncode != 0:
            fail("DNS_ROUTE_FAILED: " + (route.stderr.strip() or route.stdout.strip()), 8)

    registry[host] = {
        "app_id": app_id,
        "container": container,
        "image": tpl["image"],
        "port": host_port,
        "created_at": int(time.time()),
    }
    save_registry(registry)
    write_tunnel_config(registry)

    if launchctl:
        subprocess.run([launchctl, "kickstart", "-k", f"gui/{os.getuid()}/online.novec.appstore-tunnel"], check=False)
        time.sleep(3)

    print(json.dumps({
        "ok": True,
        "app_id": app_id,
        "subdomain": subdomain,
        "url": f"https://{host}",
        "port": host_port,
        "container": container,
    }))


if __name__ == "__main__":
    main()
