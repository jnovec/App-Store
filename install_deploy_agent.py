#!/usr/bin/env python3
import os
import plistlib
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
HOME = Path.home()
LABEL = "online.novec.appstore-deploy-agent"
PLIST = HOME / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = HOME / "Library" / "Logs"


def main():
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(BASE / "deploy_agent.py")],
        "WorkingDirectory": str(BASE),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_DIR / "novec-appstore-deploy-agent.log"),
        "StandardErrorPath": str(LOG_DIR / "novec-appstore-deploy-agent-error.log"),
    }
    with PLIST.open("wb") as f:
        plistlib.dump(data, f)

    uid = os.getuid()
    target = f"gui/{uid}/{LABEL}"
    subprocess.run(["/bin/launchctl", "bootout", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{uid}", str(PLIST)], check=True)
    subprocess.run(["/bin/launchctl", "kickstart", "-k", target], check=True)
    print(f"installed {LABEL}")


if __name__ == "__main__":
    main()
