#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from deploy_helper import executable, load_registry, save_registry, write_tunnel_config

HOME = Path.home()
BASE = HOME / "novec-app-store"
DATA = BASE / "data"
DNS_RELEASE_SECRET = DATA / "dns-release-secret.txt"
DNS_RELEASE_URL = "https://n8n.novec.online/webhook/novec-appstore-release-dns"


def log(message):
    print(message, flush=True)


def fail(message, code=1):
    log(json.dumps({"ok": False, "error": message}))
    raise SystemExit(code)


def release_dns(hostname):
    secret = DNS_RELEASE_SECRET.read_text(encoding="utf-8").strip() if DNS_RELEASE_SECRET.exists() else ""
    if not secret:
        fail("DNS_RELEASE_SECRET_MISSING", 12)
    payload = json.dumps({"hostname": hostname}).encode("utf-8")
    request = urllib.request.Request(
        DNS_RELEASE_URL,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-NOVEC-Release-Key": secret,
            "User-Agent": "NOVEC-App-Store/0.7",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", "replace")[-2000:]
        fail("DNS_RELEASE_FAILED: " + details, 13)
    except Exception as exc:
        fail("DNS_RELEASE_FAILED: " + str(exc), 13)
    if not isinstance(body, dict) or not body.get("ok"):
        fail("DNS_RELEASE_FAILED: " + json.dumps(body, ensure_ascii=False), 13)
    return body


def main():
    if len(sys.argv) != 3:
        fail("USAGE: undeploy_helper.py <hostname> <purge_data:0|1>")

    hostname = sys.argv[1].strip().lower()
    purge_data = sys.argv[2].strip() == "1"
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.novec\.online", hostname):
        fail("INVALID_HOSTNAME", 2)
    if hostname in {"store.novec.online", "n8n.novec.online", "www.novec.online", "api.novec.online", "dev.novec.online", "ssh.novec.online", "mail.novec.online"}:
        fail("RESERVED_HOSTNAME", 2)

    registry = load_registry()
    item = registry.get(hostname)
    if not isinstance(item, dict):
        fail("DEPLOYMENT_NOT_FOUND", 3)

    docker = executable("docker", ["/Applications/Docker.app/Contents/Resources/bin/docker", "/opt/homebrew/bin/docker"])
    launchctl = executable("launchctl", ["/bin/launchctl"])
    if not docker:
        fail("DOCKER_NOT_FOUND", 4)

    container = str(item.get("container") or "").strip()
    log(f"[1/6] Removing container {container or '(unknown)'}…")
    if container:
        exists = subprocess.run([docker, "inspect", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if exists.returncode == 0:
            subprocess.run([docker, "rm", "-f", container], check=True)
        else:
            log("Container is already absent.")

    log("[2/6] Persistent data policy: " + ("DELETE volumes" if purge_data else "KEEP volumes"))
    removed_volumes = []
    if purge_data and container:
        try:
            volume_names = subprocess.check_output([docker, "volume", "ls", "--format", "{{.Name}}"], text=True).splitlines()
        except Exception:
            volume_names = []
        prefixes = (f"{container}-data", f"{container}_data")
        for volume in volume_names:
            if any(volume == prefix or volume.startswith(prefix + "-") for prefix in prefixes):
                subprocess.run([docker, "volume", "rm", volume], check=False)
                removed_volumes.append(volume)
                log("Removed volume: " + volume)

    log(f"[3/6] Releasing Cloudflare DNS hostname {hostname}…")
    dns_result = release_dns(hostname)
    log("DNS release: " + ("record deleted" if dns_result.get("deleted") else "record already absent"))

    log("[4/6] Removing deployment from NOVEC registry…")
    registry.pop(hostname, None)
    save_registry(registry)

    log("[5/6] Updating Cloudflare tunnel ingress…")
    write_tunnel_config(registry)
    if launchctl:
        subprocess.run([launchctl, "kickstart", "-k", f"gui/{os.getuid()}/online.novec.appstore-tunnel"], check=False)
        time.sleep(2)

    log("[6/6] Deployment removed and hostname released.")
    print(json.dumps({
        "ok": True,
        "action": "undeploy",
        "hostname": hostname,
        "url": f"https://{hostname}",
        "container": container,
        "purge_data": purge_data,
        "removed_volumes": removed_volumes,
        "dns_deleted": bool(dns_result.get("deleted")),
    }), flush=True)


if __name__ == "__main__":
    main()
