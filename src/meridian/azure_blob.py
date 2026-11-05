"""Minimal Azure Blob Storage client over the REST API, authorised by a SAS URL.

Only the operations the backup command needs are implemented: upload a block blob and
list blobs under a prefix. Requests use the standard library, so no Azure SDK is needed.
A shared access signature (SAS) grants time-limited access without account keys.
"""

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass

from meridian.models import InputError

API_VERSION = "2023-11-03"
REQUEST_TIMEOUT_SECONDS = 30
MAX_BLOB_BYTES = 256 * 1024 * 1024
CONTENT_TYPES = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".html": "text/html",
}


@dataclass(frozen=True)
class SasLocation:
    """A storage account endpoint and the SAS token that authorises requests to it."""

    endpoint: str
    token: str

    def blob_url(self, container: str, name: str) -> str:
        """Full URL of a blob, including the SAS token."""
        quoted = urllib.parse.quote(name, safe="/")
        return f"{self.endpoint}/{container}/{quoted}?{self.token}"

    def container_url(self, container: str, query: dict[str, str]) -> str:
        """URL of a container operation, with its query parameters and the SAS token."""
        return f"{self.endpoint}/{container}?{urllib.parse.urlencode(query)}&{self.token}"


def parse_sas_url(url: str) -> SasLocation:
    """Split an account SAS URL (https://<account>.blob.core.windows.net/?sv=...&sig=...)."""
    if not isinstance(url, str) or not url:
        raise InputError("A SAS URL is required")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise InputError("The SAS URL must use https")
    if not parts.netloc.endswith(".blob.core.windows.net"):
        raise InputError("The SAS URL must point to <account>.blob.core.windows.net")
    query = urllib.parse.parse_qs(parts.query)
    if "sig" not in query or "sv" not in query:
        raise InputError("The SAS URL must include its token (sv=... and sig=...)")
    return SasLocation(f"https://{parts.netloc}", parts.query)


def content_type(name: str) -> str:
    """MIME type for a bundle file, by extension."""
    for suffix, kind in CONTENT_TYPES.items():
        if name.endswith(suffix):
            return kind
    return "application/octet-stream"


def put_blob(location: SasLocation, container: str, name: str, data: bytes) -> int:
    """Upload ``data`` as a block blob and return the HTTP status (201 on success).

    Raises urllib.error.HTTPError for error responses so callers can decide on retries.
    """
    if len(data) > MAX_BLOB_BYTES:
        raise InputError(f"{name} is larger than {MAX_BLOB_BYTES // (1024 * 1024)} MB")
    request = urllib.request.Request(
        location.blob_url(container, name),
        data=data,
        method="PUT",
        headers={
            "x-ms-blob-type": "BlockBlob",
            "x-ms-version": API_VERSION,
            "Content-Type": content_type(name),
            "Content-Length": str(len(data)),
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.status


def list_blobs(location: SasLocation, container: str, prefix: str = "") -> list[str]:
    """Names of blobs in a container under ``prefix``, following continuation markers."""
    names = []
    marker = ""
    while True:
        query = {"restype": "container", "comp": "list", "prefix": prefix}
        if marker:
            query["marker"] = marker
        request = urllib.request.Request(
            location.container_url(container, query), headers={"x-ms-version": API_VERSION}
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            raise InputError(f"Unexpected response listing {container}: {exc}") from exc
        names.extend(element.text for element in root.iter("Name") if element.text)
        marker = root.findtext("NextMarker") or ""
        if not marker:
            return names


def get_blob(location: SasLocation, container: str, name: str) -> bytes:
    """Download a blob's contents. Raises urllib.error.HTTPError when it does not exist."""
    request = urllib.request.Request(
        location.blob_url(container, name), headers={"x-ms-version": API_VERSION}
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        data = response.read(MAX_BLOB_BYTES + 1)
    if len(data) > MAX_BLOB_BYTES:
        raise InputError(f"{name} is larger than {MAX_BLOB_BYTES // (1024 * 1024)} MB")
    return data


def bundle_names(blob_names: list[str]) -> list[str]:
    """Distinct top-level folder names (bundles) among blob names, sorted."""
    return sorted({name.split("/", 1)[0] for name in blob_names if "/" in name})
