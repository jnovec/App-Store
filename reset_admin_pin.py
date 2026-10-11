#!/usr/bin/env python3
import os
import secrets
from pathlib import Path

BASE = Path(__file__).resolve().parent
PIN_FILE = BASE / "data" / "admin-pin.txt"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
pin = "".join(secrets.choice(ALPHABET) for _ in range(10))
PIN_FILE.write_text(pin, encoding="utf-8")
os.chmod(PIN_FILE, 0o600)
print(pin)
