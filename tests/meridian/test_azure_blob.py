"""Azure Blob Storage REST client."""

import io
import urllib.parse

import pytest

from meridian import azure_blob
from meridian.models import InputError

SAS = "https://meridianbackup.blob.core.windows.net/?sv=2023-11-03&ss=b&srt=co&sp=rwl&sig=abc%2Bdef"


class _Response(io.BytesIO):
    def __init__(self, body=b"", status=201):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_parse_sas_url():
    location = azure_blob.parse_sas_url(SAS)
    assert location.endpoint == "https://meridianbackup.blob.core.windows.net"
    assert location.token.startswith("sv=2023-11-03")


@pytest.mark.parametrize(
    "url, message",
    [
        ("", "required"),
        ("http://meridianbackup.blob.core.windows.net/?sv=1&sig=2", "https"),
        ("https://example.com/?sv=1&sig=2", "blob.core.windows.net"),
        ("https://meridianbackup.blob.core.windows.net/?sv=1", "token"),
    ],
)
def test_invalid_sas_url(url, message):
    with pytest.raises(InputError, match=message):
        azure_blob.parse_sas_url(url)


def test_blob_url_quotes_names():
    location = azure_blob.parse_sas_url(SAS)
    url = location.blob_url("results", "run 1/summary.json")
    assert url.startswith(
        "https://meridianbackup.blob.core.windows.net/results/run%201/summary.json?"
    )
    assert url.endswith(location.token)


def test_container_url():
    location = azure_blob.parse_sas_url(SAS)
    url = location.container_url("results", {"restype": "container", "comp": "list"})
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert query["restype"] == ["container"] and query["comp"] == ["list"]
    assert "sig" in query


@pytest.mark.parametrize(
    "name, kind",
    [
        ("a/summary.json", "application/json"),
        ("a/lanes.csv", "text/csv"),
        ("a/report.md", "text/markdown"),
        ("a/report.html", "text/html"),
        ("a/data.bin", "application/octet-stream"),
    ],
)
def test_content_type(name, kind):
    assert azure_blob.content_type(name) == kind


def test_put_blob_request(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return _Response(status=201)

    monkeypatch.setattr(azure_blob.urllib.request, "urlopen", fake_urlopen)
    location = azure_blob.parse_sas_url(SAS)
    status = azure_blob.put_blob(location, "results", "run/summary.json", b"{}")
    request = seen["request"]
    assert status == 201
    assert request.get_method() == "PUT"
    assert request.get_header("X-ms-blob-type") == "BlockBlob"
    assert request.get_header("Content-type") == "application/json"
    assert request.data == b"{}"
    assert seen["timeout"] == azure_blob.REQUEST_TIMEOUT_SECONDS


def test_put_blob_size_limit(monkeypatch):
    monkeypatch.setattr(azure_blob, "MAX_BLOB_BYTES", 4)
    with pytest.raises(InputError, match="larger than"):
        azure_blob.put_blob(azure_blob.parse_sas_url(SAS), "results", "big.bin", b"12345")


def _listing(names, marker=""):
    blobs = "".join(f"<Blob><Name>{name}</Name></Blob>" for name in names)
    return (
        f"<?xml version='1.0' encoding='utf-8'?><EnumerationResults><Blobs>{blobs}</Blobs>"
        f"<NextMarker>{marker}</NextMarker></EnumerationResults>"
    ).encode()


def test_list_blobs_follows_markers(monkeypatch):
    pages = [_listing(["a/summary.json"], marker="page2"), _listing(["b/summary.json"])]
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        return _Response(pages.pop(0), status=200)

    monkeypatch.setattr(azure_blob.urllib.request, "urlopen", fake_urlopen)
    names = azure_blob.list_blobs(azure_blob.parse_sas_url(SAS), "results", prefix="")
    assert names == ["a/summary.json", "b/summary.json"]
    assert "marker=page2" in urls[1]


def test_list_blobs_bad_xml(monkeypatch):
    monkeypatch.setattr(
        azure_blob.urllib.request, "urlopen", lambda request, timeout: _Response(b"<oops", 200)
    )
    with pytest.raises(InputError, match="Unexpected response"):
        azure_blob.list_blobs(azure_blob.parse_sas_url(SAS), "results")


def test_get_blob(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        return _Response(b"payload", status=200)

    monkeypatch.setattr(azure_blob.urllib.request, "urlopen", fake_urlopen)
    data = azure_blob.get_blob(azure_blob.parse_sas_url(SAS), "results", "run/summary.json")
    assert data == b"payload"
    assert "/results/run/summary.json?" in seen["url"]


def test_get_blob_size_limit(monkeypatch):
    monkeypatch.setattr(azure_blob, "MAX_BLOB_BYTES", 3)
    monkeypatch.setattr(
        azure_blob.urllib.request, "urlopen", lambda request, timeout: _Response(b"abcd", 200)
    )
    with pytest.raises(InputError, match="larger than"):
        azure_blob.get_blob(azure_blob.parse_sas_url(SAS), "results", "big.bin")


def test_bundle_names():
    names = ["b-1/summary.json", "a-2/summary.json", "a-2/lanes.csv", "loose.txt"]
    assert azure_blob.bundle_names(names) == ["a-2", "b-1"]


def test_put_blob_content_length(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["request"] = request
        return _Response(status=201)

    monkeypatch.setattr(azure_blob.urllib.request, "urlopen", fake_urlopen)
    azure_blob.put_blob(azure_blob.parse_sas_url(SAS), "results", "run/lanes.csv", b"a,b\n1,2\n")
    assert seen["request"].get_header("Content-length") == "8"
    assert seen["request"].get_header("X-ms-version") == azure_blob.API_VERSION


def test_list_blobs_prefix_in_query(monkeypatch):
    urls = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        return _Response(_listing(["run-1/a.json"]), status=200)

    monkeypatch.setattr(azure_blob.urllib.request, "urlopen", fake_urlopen)
    azure_blob.list_blobs(azure_blob.parse_sas_url(SAS), "results", prefix="run-1/")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(urls[0]).query)
    assert query["prefix"] == ["run-1/"]
