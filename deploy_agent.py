#!/usr/bin/env python3
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
SECRET_FILE = DATA / "deploy-agent-secret.txt"
HELPER = BASE / "deploy_helper.py"
HOST = "0.0.0.0"
PORT = 18791


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(fmt % args, flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"ok": False, "error": "NOT_FOUND"})

    def do_POST(self):
        if self.path != "/deploy":
            self.send_json(404, {"ok": False, "error": "NOT_FOUND"})
            return

        expected = SECRET_FILE.read_text(encoding="utf-8").strip() if SECRET_FILE.exists() else ""
        supplied = self.headers.get("X-NOVEC-Agent-Secret", "")
        if not expected or supplied != expected:
            self.send_json(403, {"ok": False, "error": "FORBIDDEN"})
            return

        try:
            length = min(int(self.headers.get("Content-Length", "0")), 8192)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            app_id = str(payload.get("app_id", ""))
            subdomain = str(payload.get("subdomain", ""))
        except Exception:
            self.send_json(400, {"ok": False, "error": "INVALID_JSON"})
            return

        try:
            result = subprocess.run(
                [sys.executable, str(HELPER), app_id, subdomain],
                cwd=str(BASE),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            self.send_json(504, {"ok": False, "error": "DEPLOY_TIMEOUT"})
            return

        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        response = None
        if lines:
            try:
                response = json.loads(lines[-1])
            except Exception:
                response = None

        if result.returncode != 0 or not isinstance(response, dict):
            self.send_json(500, {
                "ok": False,
                "error": (response or {}).get("error", "DEPLOY_FAILED"),
                "details": (result.stderr or result.stdout)[-3000:],
            })
            return

        self.send_json(200, response)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"NOVEC deploy agent listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
