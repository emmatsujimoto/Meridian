"""Results API responses for authorized and unauthorized requests."""

import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from meridian.server import make_handler


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MERIDIAN_API_KEY", "test-key")
    (tmp_path / "run-1").mkdir()
    (tmp_path / "run-1" / "summary.json").write_text('{"scenario_id": "run"}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def get(url, key):
    request = urllib.request.Request(url, headers={"X-API-Key": key})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, response.read()


def test_authorized_request_returns_summary(api):
    status, body = get(f"{api}/run-1/summary.json", "test-key")
    assert status == 200
    assert b"scenario_id" in body


def test_wrong_key_rejected(api):
    with pytest.raises(urllib.error.HTTPError) as error:
        get(f"{api}/run-1/summary.json", "wrong")
    assert error.value.code == 401


def test_missing_file_is_404(api):
    with pytest.raises(urllib.error.HTTPError) as error:
        get(f"{api}/run-1/missing.json", "test-key")
    assert error.value.code == 404
