#!/usr/bin/env python3
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from template_catalog import load_templates

TUNNEL_ID = "76ba2ac9-7bde-4986-bed8-1d1c17710006"
HOME = Path.home()
BASE = HOME / "novec-app-store"
DATA = BASE / "data"
REGISTRY = DATA / "deployments.json"
TUNNEL_CONFIG = HOME / ".cloudflared" / "novec-app-store-config.yml"
RESERVED = {"store", "n8n", "www", "api", "dev", "ssh", "mail"}


def log(message):
    print(message, flush=True)


def fail(message, code=1):
    log(json.dumps({"ok": False, "error": message}))
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
        if not isinstance(item, dict) or not item.get('port'):
            continue
        lines += [
            f"  - hostname: {host}",
            f"    service: http://127.0.0.1:{int(item['port'])}",
        ]
    lines += ["  - service: http_status:404", ""]
    TUNNEL_CONFIG.write_text("\n".join(lines), encoding="utf-8")


def wait_port(port, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=2):
                return True
        except OSError:
            time.sleep(2)
    return False


def safe_name(value):
    return ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in value.lower()).strip('-')[:80]


def run(cmd, check=True):
    shown = ' '.join(shlex.quote(str(x)) for x in cmd)
    log(f"$ {shown}")
    return subprocess.run(cmd, check=check)


def main():
    if len(sys.argv) not in (3, 4):
        fail("USAGE: deploy_helper.py <app_id> <subdomain> [template_key]")

    app_id = sys.argv[1].strip().lower()
    subdomain = sys.argv[2].strip().lower()
    template_key = (sys.argv[3].strip().lower() if len(sys.argv) == 4 else app_id)

    if not subdomain or len(subdomain) > 63 or subdomain in RESERVED:
        fail("INVALID_OR_RESERVED_SUBDOMAIN", 3)
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in subdomain):
        fail("INVALID_SUBDOMAIN", 3)
    if subdomain.startswith("-") or subdomain.endswith("-"):
        fail("INVALID_SUBDOMAIN", 3)

    log("[1/7] Loading reviewed deployment template…")
    templates = load_templates(DATA)
    tpl = templates.get(template_key)
    if not tpl:
        fail("APP_NOT_ONE_CLICK_READY", 2)

    docker = executable("docker", ["/Applications/Docker.app/Contents/Resources/bin/docker", "/opt/homebrew/bin/docker"])
    cloudflared = executable("cloudflared", ["/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared"])
    launchctl = executable("launchctl", ["/bin/launchctl"])
    if not docker:
        fail("DOCKER_NOT_FOUND", 4)
    if not cloudflared:
        fail("CLOUDFLARED_NOT_FOUND", 5)

    host = f"{subdomain}.novec.online"
    container = safe_name(f"novec-{app_id}-{subdomain}")
    registry = load_registry()

    log(f"[2/7] Pulling image {tpl['image']}…")
    inspect = subprocess.run([docker, "inspect", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if inspect.returncode != 0:
        run([docker, "pull", tpl["image"]])

        log("[3/7] Creating Docker container…")
        cmd = [
            docker, "run", "-d",
            "--name", container,
            "--restart", str(tpl.get('restart_policy') or 'unless-stopped'),
            "-p", f"127.0.0.1::{int(tpl['port'])}",
        ]
        for i, volume in enumerate(tpl.get('volumes') or []):
            cmd += ["-v", f"{container}-data-{i + 1}:{volume}"]
        for key, value in (tpl.get('env') or {}).items():
            cmd += ["-e", f"{key}={value}"]
        cmd += [tpl["image"]]
        command = tpl.get('command')
        if command:
            if isinstance(command, list):
                cmd += [str(x) for x in command]
            else:
                cmd += shlex.split(str(command))
        run(cmd)
    else:
        log("[3/7] Existing container found, starting it…")
        subprocess.run([docker, "start", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    log("[4/7] Waiting for application port…")
    port_out = subprocess.check_output([docker, "port", container, f"{int(tpl['port'])}/tcp"], text=True).strip().splitlines()
    if not port_out:
        fail("HOST_PORT_NOT_FOUND", 6)
    host_port = int(port_out[0].rsplit(":", 1)[1])
    if not wait_port(host_port):
        logs = subprocess.run([docker, "logs", "--tail", "120", container], capture_output=True, text=True)
        if logs.stdout:
            log(logs.stdout[-6000:])
        if logs.stderr:
            log(logs.stderr[-6000:])
        fail("APP_HEALTH_TIMEOUT", 7)

    log(f"[5/7] Registering Cloudflare hostname {host}…")
    if host not in registry:
        route = subprocess.run([cloudflared, "tunnel", "route", "dns", TUNNEL_ID, host], capture_output=True, text=True)
        if route.stdout:
            log(route.stdout.strip())
        if route.returncode != 0:
            fail("DNS_ROUTE_FAILED: " + (route.stderr.strip() or route.stdout.strip()), 8)

    registry[host] = {
        "app_id": app_id,
        "template_key": template_key,
        "name": tpl.get('title') or app_id,
        "container": container,
        "image": tpl["image"],
        "port": host_port,
        "url": f"https://{host}",
        "status": "running",
        "created_at": registry.get(host, {}).get('created_at') or int(time.time()),
        "updated_at": int(time.time()),
    }
    save_registry(registry)

    log("[6/7] Updating Cloudflare ingress…")
    write_tunnel_config(registry)
    if launchctl:
        subprocess.run([launchctl, "kickstart", "-k", f"gui/{os.getuid()}/online.novec.appstore-tunnel"], check=False)
        time.sleep(2)

    log("[7/7] Deployment finished.")
    print(json.dumps({
        "ok": True,
        "app_id": app_id,
        "template_key": template_key,
        "subdomain": subdomain,
        "url": f"https://{host}",
        "port": host_port,
        "container": container,
        "image": tpl["image"],
    }), flush=True)


if __name__ == "__main__":
    main()
