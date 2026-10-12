#!/usr/bin/env python3
import json
import re
import subprocess
import sys
from pathlib import Path

from deploy_helper import executable, load_registry, save_registry, write_tunnel_config

HOME = Path.home()


def log(message):
    print(message, flush=True)


def fail(message, code=1):
    log(json.dumps({"ok": False, "error": message}))
    raise SystemExit(code)


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
    if not docker:
        fail("DOCKER_NOT_FOUND", 4)

    container = str(item.get("container") or "").strip()
    log(f"[1/5] Removing container {container or '(unknown)'}…")
    if container:
        exists = subprocess.run([docker, "inspect", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if exists.returncode == 0:
            subprocess.run([docker, "rm", "-f", container], check=True)
        else:
            log("Container is already absent.")

    log("[2/5] Persistent data policy: " + ("DELETE volumes" if purge_data else "KEEP volumes"))
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

    log("[3/5] Removing deployment from NOVEC registry…")
    registry.pop(hostname, None)
    save_registry(registry)

    log(f"[4/5] Updating desired Cloudflare ingress for {hostname} without restarting the App Store tunnel…")
    write_tunnel_config(registry)

    log("[5/5] Deployment removed. Hostname is free for reuse by NOVEC App Store.")
    print(json.dumps({
        "ok": True,
        "action": "undeploy",
        "hostname": hostname,
        "url": f"https://{hostname}",
        "container": container,
        "purge_data": purge_data,
        "removed_volumes": removed_volumes,
        "hostname_reusable": True,
        "tunnel_restart_deferred": True,
    }), flush=True)


if __name__ == "__main__":
    main()
