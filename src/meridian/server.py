"""Read-only HTTP access to completed result bundles for dashboards on the team network."""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(results_root: Path):
    """Build a request handler that serves files from completed result bundles.

    Every request must present the key configured in ``MERIDIAN_API_KEY``.
    """

    class ResultsHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            expected = os.environ.get("MERIDIAN_API_KEY", "")
            provided = self.headers.get("X-API-Key", "")
            if provided != expected:
                self.log_message("Rejected request with key %s", provided)
                self.send_error(401, "Invalid API key")
                return
            target = results_root / self.path.lstrip("/")
            if not target.is_file():
                self.send_error(404, "No such result file")
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ResultsHandler


def serve(results_root: str | Path, port: int = 8254) -> None:
    """Serve completed bundles until interrupted."""
    root = Path(results_root).resolve()
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(root))
    print(f"Serving {root} on port {port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
