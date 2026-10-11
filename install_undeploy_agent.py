#!/usr/bin/env python3
import os
import plistlib
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
HOME = Path.home()
LABEL = "online.novec.appstore-undeploy-agent"
PLIST = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = HOME / "Library" / "Logs"
DATA = BASE / "data"
AGENT_SECRET = DATA / "deploy-agent-secret.txt"


def main():
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    if not AGENT_SECRET.exists() or not AGENT_SECRET.read_text(encoding="utf-8").strip():
        raise SystemExit("deploy-agent-secret.txt is missing; install deploy agent first")

    data = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(BASE / "undeploy_agent.py")],
        "WorkingDirectory": str(BASE),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_DIR / "novec-appstore-undeploy-agent.log"),
        "StandardErrorPath": str(LOG_DIR / "novec-appstore-undeploy-agent-error.log"),
    }
    with PLIST.open("wb") as handle:
        plistlib.dump(data, handle)

    uid = os.getuid()
    target = f"gui/{uid}/{LABEL}"
    subprocess.run(["/bin/launchctl", "bootout", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{uid}", str(PLIST)], check=True)
    subprocess.run(["/bin/launchctl", "kickstart", "-k", target], check=True)
    print(f"installed {LABEL}")


if __name__ == "__main__":
    main()
