"""End-to-end add-in wiring against a live OpenAI-compatible server (a mock that
speaks the same /v1 protocol an edgemesh gateway / the Cognis fleet does)."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from maritimeint import addins
from maritimeint.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIS = os.path.join(ROOT, "demos", "ais_sample.json")


class _MockOAI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/v1/models"):
            self._send({"data": [{"id": "test-model"}]})
        else:
            self._send({}, 404)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._send({"choices": [{"message": {"role": "assistant",
                    "content": "ASSESSMENT: prioritize the sanctioned vessel for review."}}]})


@pytest.fixture()
def gateway():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockOAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def test_addins_discover_against_live_endpoint(gateway):
    # availability probing finds a reachable backend (edgemesh maps to this port in real use)
    models = addins.probe(gateway)
    assert models == ["test-model"]


def test_reasoning_addin_end_to_end(gateway, capsys):
    rc = main(["--format", "json", "locate", AIS, "--endpoint", gateway, "--model", "test-model"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "ASSESSMENT: prioritize" in out["ai_assessment"]
    assert out["watchlist"][0]["mmsi"] == "210111000"   # core still ran


def test_vision_addin_end_to_end(gateway, capsys):
    rc = main(["vision", "https://example.org/sentinel1_scene.png",
               "--endpoint", gateway, "--model", "test-model"])
    assert rc == 0
    assert "ASSESSMENT" in capsys.readouterr().out


def test_vision_no_backend_fails_gracefully(capsys):
    rc = main(["vision", "https://example.org/x.png", "--endpoint", "http://127.0.0.1:1"])
    assert rc == 1
    assert "error" in capsys.readouterr().err.lower()
