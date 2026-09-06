#!/usr/bin/env python3
"""Collect evidence posted by the Windows guest probe, and screendump on each.

The guest reaches the host at 10.0.2.2 through QEMU's user-mode NAT, so the
probe running inside Sublime Text can hand its JSON back without any shared
filesystem. Every arrival is written to the evidence directory and answered
only after a screendump, so the picture belongs to the phase that posted it.

    python3 ~/vm/collector.py --evidence <dir> [--port 8099]
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MONITOR = os.path.expanduser("~/vm/win11/monitor.sock")


def monitor(command):
    """One HMP command over the QEMU monitor socket."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(10)
        sock.connect(MONITOR)
        time.sleep(0.2)
        try:
            sock.recv(65536)
        except socket.timeout:
            pass
        sock.sendall((command + "\n").encode())
        time.sleep(0.5)
        try:
            return sock.recv(65536).decode("utf-8", "replace")
        except socket.timeout:
            return ""


def screendump(directory, name):
    ppm = os.path.join(directory, name + ".ppm")
    monitor("screendump " + ppm)
    for _ in range(40):
        if os.path.exists(ppm) and os.path.getsize(ppm) > 0:
            break
        time.sleep(0.25)
    png = os.path.join(directory, name + ".png")
    try:
        subprocess.run(["convert", ppm, png], check=True, capture_output=True)
        os.remove(ppm)
        return png
    except Exception as error:  # noqa: BLE001 - keep the ppm if convert is absent
        print("  convert failed ({}), keeping {}".format(error, ppm))
        return ppm


class Handler(BaseHTTPRequestHandler):
    evidence = "."

    def log_message(self, *args):  # quieter than the default access log
        pass

    def _reply(self, text, status=200):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply("collector alive\n")

    def do_POST(self):
        if not self.path.startswith("/evidence/"):
            return self._reply("unknown path\n", 404)
        name = os.path.basename(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError:
            payload = {"raw": raw.decode("utf-8", "replace")}

        # The exported page is a document in its own right; keep it beside
        # the JSON rather than embedded in it.
        page = payload.get("page")
        if isinstance(page, str):
            with open(os.path.join(self.evidence, name + ".html"), "w", encoding="utf-8") as sink:
                sink.write(page)
            payload["page"] = "written to {}.html ({} bytes)".format(name, len(page))
        body = payload.get("body_html")
        if isinstance(body, str):
            with open(os.path.join(self.evidence, name + "-body.html"), "w", encoding="utf-8") as sink:
                sink.write(body)
            payload["body_html"] = "written to {}-body.html ({} bytes)".format(name, len(body))

        with open(os.path.join(self.evidence, name + ".json"), "w", encoding="utf-8") as sink:
            json.dump(payload, sink, indent=2, sort_keys=True)
        shot = screendump(self.evidence, name)
        print("{}  {} -> {}".format(time.strftime("%H:%M:%S"), name, os.path.basename(shot)))
        sys.stdout.flush()
        self._reply("go\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    os.makedirs(args.evidence, exist_ok=True)
    Handler.evidence = args.evidence
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print("collector on :{} -> {}".format(args.port, args.evidence))
    sys.stdout.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
