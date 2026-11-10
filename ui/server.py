"""Local test UI: a small web page that sends questions through pipeline.answer().

Usage: uv run python ui/server.py [--port 8000]   then open http://127.0.0.1:8000
Standard library only; binds to localhost.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import structlog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops import metrics  # noqa: E402
from pipeline import answer  # noqa: E402
from plantdb.plants import build_plant_databases  # noqa: E402

MAX_ROWS = 200
MAX_BODY = 10_000
TODAY = date(2026, 9, 15)  # the data covers 2026-06-01 to 2026-08-30
PAGE = Path(__file__).with_name("index.html")


def run_query(query: str, databases: dict, confirmed: bool) -> dict:
    res = answer(query, databases, today=TODAY, confirmed=confirmed)
    out: dict = {
        "status": res.status,
        "message": res.message,
        "intent": res.intent.intent_type.value,
        "confidence": round(res.intent.confidence, 2),
        "trace_id": res.trace_id,
        "code": res.code,
        "branches": [
            {
                "plant": b.plant,
                "variant": b.variant,
                "ms": round(b.ms, 1),
                "rows": b.rows,
                "error": b.error,
            }
            for b in res.branches
        ],
    }
    if res.frame is not None:
        out["table"] = json.loads(
            res.frame.head(MAX_ROWS).to_json(orient="split", date_format="iso")
        )
        out["total_rows"] = len(res.frame)
    return out


def make_handler(databases: dict) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/metrics":
                self._send(200, metrics.render_prometheus().encode(), "text/plain; version=0.0.4")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            if self.path != "/ask":
                return self._send(404, b"not found", "text/plain")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._send(413, b"too large", "text/plain")
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                query = str(body.get("query", "")).strip()
                if not query:
                    raise ValueError("empty question")
                result = run_query(query, databases, bool(body.get("confirmed")))
            except Exception as e:  # the UI should show the problem, not drop the connection
                result = {"status": "error", "message": f"{type(e).__name__}: {e}"}
            self._send(200, json.dumps(result).encode(), "application/json")

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(50))
    databases = build_plant_databases(Path(tempfile.mkdtemp(prefix="lattice-ui-")))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(databases))
    print(f"Lattice UI on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    server.serve_forever()


if __name__ == "__main__":
    main()
