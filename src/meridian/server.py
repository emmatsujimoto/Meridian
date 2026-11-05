"""A small read-only results API for completed result bundles.

Every request needs the API key from the MERIDIAN_API_KEY environment variable in the
``X-API-Key`` header. Bundles are only read through ``verify_bundle``, so a modified
bundle is never served.

Endpoints:

- ``GET /health``: liveness check (no key needed).
- ``GET /results``: completed bundles under the results folder, newest first.
- ``GET /results/<name>``: one bundle's summary.
- ``POST /what-if/capacity``: allocations of proposed plant capacities for one bundle.
"""

import hmac
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from meridian.bundles import verify_bundle
from meridian.models import InputError
from meridian.whatif import PRODUCTS, allocate, allocation_rows, allocation_summary, lane_demands

API_KEY_ENV = "MERIDIAN_API_KEY"
BUNDLE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}-[0-9a-f]{12}")
MAX_LIMIT = 100


def api_key_from_environment(environ: dict | None = None) -> str:
    """The configured API key; at least 16 characters so it cannot be guessed easily."""
    values = os.environ if environ is None else environ
    key = values.get(API_KEY_ENV, "")
    if len(key) < 16:
        raise InputError(f"Set {API_KEY_ENV} to an API key of at least 16 characters")
    return key


def _bundle_summary(root: Path, name: str) -> dict:
    """A verified bundle's summary by folder name; names cannot leave the results root."""
    if not BUNDLE_NAME.fullmatch(name):
        raise LookupError(name)
    path = root / name / "summary.json"
    if not path.is_file():
        raise LookupError(name)
    return verify_bundle(path)


def list_results(root: Path, product: str | None = None, limit: int = 20) -> list[dict]:
    """Completed bundles under ``root``, newest first, optionally with lanes of one product."""
    rows = []
    for folder in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not folder.is_dir() or not (folder / "COMPLETE.json").is_file():
            continue
        try:
            report = _bundle_summary(root, folder.name)
        except (LookupError, InputError):
            continue
        lanes = [row["lane"] for row in report["lanes"]]
        if product is not None and not any(lane.endswith(f":{product}") for lane in lanes):
            continue
        rows.append(
            {
                "name": folder.name,
                "scenario_id": report["scenario_id"],
                "horizon_days": report["horizon_days"],
                "total_mean_cost": report["total_mean_cost"],
                "portfolio_fill_rate": report["portfolio_fill_rate"],
                "lanes": len(lanes),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def make_handler(results_root: str | Path, api_key: str) -> type[BaseHTTPRequestHandler]:
    """A request handler class bound to one results folder and API key."""
    root = Path(results_root).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MeridianResults/1"

        def log_message(self, format: str, *args) -> None:
            """Silence the default per-request logging to stderr."""

        def sendJson(self, status: int, body: object, headers: dict | None = None) -> None:
            data = json.dumps(body, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def sendError(self, status: int, message: str, headers: dict | None = None) -> None:
            self.sendJson(status, {"error": message}, headers)

        def isAuthorised(self) -> bool:
            supplied = self.headers.get("X-API-Key", "")
            return hmac.compare_digest(supplied.encode(), api_key.encode())

        def readBody(self) -> object:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            try:
                return json.loads(raw or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise InputError(f"Request body must be JSON: {exc}") from exc

        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            if parts.path == "/health":
                self.sendJson(200, {"status": "ok"})
                return
            if not self.isAuthorised():
                self.sendError(401, "Missing or invalid API key")
                return
            query = parse_qs(parts.query)
            product = query.get("product", [None])[0]
            if product is not None and product not in PRODUCTS:
                self.sendError(400, f"product must be one of {', '.join(PRODUCTS)}")
                return
            try:
                limit = int(query.get("limit", ["20"])[0])
            except ValueError:
                self.sendError(400, "limit must be a whole number")
                return
            if not 1 <= limit <= MAX_LIMIT:
                self.sendError(400, f"limit must be from 1 to {MAX_LIMIT}")
                return
            if parts.path == "/results":
                self.sendJson(200, list_results(root, product, limit))
                return
            if parts.path.startswith("/results/"):
                name = parts.path.removeprefix("/results/")
                try:
                    report = _bundle_summary(root, name)
                except LookupError:
                    self.sendError(404, "No such result bundle")
                    return
                except InputError as exc:
                    self.sendError(422, str(exc))
                    return
                if product is not None:
                    report = {
                        **report,
                        "lanes": [r for r in report["lanes"] if r["lane"].endswith(f":{product}")],
                    }
                self.sendJson(200, report)
                return
            self.sendError(404, "Not found")

        def do_POST(self) -> None:
            cors = {"Access-Control-Allow-Origin": "*"}
            parts = urlsplit(self.path)
            if parts.path != "/what-if/capacity":
                self.sendError(404, "Not found")
                return
            if not self.isAuthorised():
                self.sendError(401, "Missing or invalid API key", cors)
                return
            try:
                body = self.readBody()
            except InputError as exc:
                self.sendError(400, str(exc), cors)
                return
            if not isinstance(body, dict):
                self.sendError(400, "Request body must be a JSON object", cors)
                return
            product = body.get("product")
            if product is not None and product not in PRODUCTS:
                self.sendError(400, f"product must be one of {', '.join(PRODUCTS)}", cors)
                return
            name = body.get("bundle")
            if not isinstance(name, str):
                self.sendError(400, "bundle must name a result bundle", cors)
                return
            try:
                report = _bundle_summary(root, name)
            except LookupError:
                self.sendError(404, "No such result bundle", cors)
                return
            try:
                allocations = allocate(
                    lane_demands(report),
                    body.get("capacities"),
                    product,
                    body.get("priorities"),
                )
            except InputError as exc:
                self.sendError(422, str(exc), cors)
                return
            self.sendJson(
                200,
                {
                    "bundle": name,
                    "scenario_id": report["scenario_id"],
                    "allocations": allocation_rows(allocations),
                    "summary": allocation_summary(allocations),
                },
                cors,
            )

    return Handler


def make_server(
    results_root: str | Path, api_key: str, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    """A server for ``results_root``; call ``serve_forever`` to start handling requests."""
    root = Path(results_root)
    if not root.is_dir():
        raise InputError(f"Results folder {root} does not exist")
    return ThreadingHTTPServer((host, port), make_handler(root, api_key))
