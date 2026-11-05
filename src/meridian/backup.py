"""Back up completed result bundles to Azure Blob Storage.

Each completed bundle (a folder with COMPLETE.json) in the results folder is uploaded
under <container>/<bundle folder>/<file>. The SAS URL comes from the MERIDIAN_BACKUP_SAS_URL
environment variable, so no credentials are stored in files or settings.
"""

import hashlib as hashlib
import json
import logging
import os
import re
import urllib.error
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from meridian import azure_blob
from meridian.bundles import verify_bundle
from meridian.models import InputError

SAS_ENVIRONMENT_VARIABLE = "MERIDIAN_BACKUP_SAS_URL"
CONTAINER = "meridian-results"
logger = logging.getLogger(__name__)


class UploadError(InputError):
    """Blob storage refused an upload or could not be reached; the whole backup stops."""


@dataclass
class BackupReport:
    """What a backup run did: bundles and files uploaded, and bundles skipped as incomplete."""

    bundles: list[str] = field(default_factory=list)
    files: int = 0
    bytes: int = 0
    skipped: list[str] = field(default_factory=list)


def completed_bundles(output_root: str | Path) -> list[Path]:
    """Bundle folders in the results folder that have a completion manifest, oldest first."""
    root = Path(output_root)
    if not root.is_dir():
        raise InputError(f"Results folder not found: {root}")
    return sorted(
        (path.parent for path in root.glob("*/COMPLETE.json")),
        key=lambda folder: folder.name,
    )


def sas_location_from_environment() -> azure_blob.SasLocation:
    """The backup destination from MERIDIAN_BACKUP_SAS_URL."""
    url = os.environ.get(SAS_ENVIRONMENT_VARIABLE)
    if not url:
        raise InputError(
            f"Set {SAS_ENVIRONMENT_VARIABLE} to a SAS URL for the storage account "
            "(write and list permissions on the backup container)"
        )
    return azure_blob.parse_sas_url(url)


def _upload_with_retry(
    location: azure_blob.SasLocation, container: str, name: str, data: bytes
) -> None:
    attempt = 0
    while True:
        attempt += 1
        try:
            azure_blob.put_blob(location, container, name, data)
            return
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404, 409, 413):
                raise UploadError(f"Upload of {name} rejected (HTTP {exc.code})") from exc
            logger.warning("Upload of %s failed (HTTP %s); retry %d", name, exc.code, attempt)
        except urllib.error.URLError as exc:
            raise UploadError(f"Cannot reach blob storage: {exc.reason}") from exc


def backup_bundle(location: azure_blob.SasLocation, bundle: Path, report: BackupReport) -> None:
    """Verify one bundle and upload all of its files."""
    verify_bundle(bundle / "summary.json")
    for path in sorted(bundle.iterdir()):
        if not path.is_file():
            continue
        data = path.read_bytes()
        name = f"{bundle.name}/{path.name}"
        logger.info("Uploading %s to %s", name, location.blob_url(CONTAINER, name))
        _upload_with_retry(location, CONTAINER, name, data)
        report.files += 1
        report.bytes += len(data)
    report.bundles.append(bundle.name)


def backup(
    output_root: str | Path, dry_run: bool = False, only: list[str] | None = None
) -> BackupReport:
    """Upload every completed, verified bundle in the results folder.

    Bundles that fail verification are skipped and reported, so one damaged bundle does
    not stop the backup of the rest. With ``dry_run`` nothing is uploaded. ``only`` limits
    the backup to the named bundle folders.
    """
    report = BackupReport()
    bundles = completed_bundles(output_root)
    if only:
        available = {bundle.name for bundle in bundles}
        missing = sorted(set(only) - available)
        if missing:
            raise InputError(f"No completed bundle named: {', '.join(missing)}")
        bundles = [bundle for bundle in bundles if bundle.name in set(only)]
    location = None if dry_run else sas_location_from_environment()
    for bundle in bundles:
        if dry_run:
            try:
                verify_bundle(bundle / "summary.json")
            except InputError:
                report.skipped.append(bundle.name)
                continue
            report.bundles.append(bundle.name)
            report.files += sum(1 for path in bundle.iterdir() if path.is_file())
            continue
        try:
            backup_bundle(location, bundle, report)
        except UploadError:
            raise
        except InputError as exc:
            logger.warning("Skipping %s: %s", bundle.name, exc)
            report.skipped.append(bundle.name)
    return report


LOG_FILE = "backup_log.json"


def write_log(output_root: str | Path, report: BackupReport) -> Path:
    """Append this run to backup_log.json in the results folder and return its path.

    The log records when each backup ran and what it uploaded, so a team can see when
    results were last safeguarded without opening the storage account.
    """
    path = Path(output_root) / LOG_FILE
    entries = []
    if path.is_file():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise InputError(f"{LOG_FILE} is not valid JSON: {exc}") from exc
        if not isinstance(entries, list):
            raise InputError(f"{LOG_FILE} must contain a list")
    entries.append({"completed_utc": datetime.now(timezone.utc).isoformat(), **asdict(report)})
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return path


def remote_bundles() -> list[str]:
    """Bundles already present in the backup container."""
    location = sas_location_from_environment()
    try:
        names = azure_blob.list_blobs(location, CONTAINER)
    except urllib.error.HTTPError as exc:
        raise UploadError(f"Cannot list the backup container (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"Cannot reach blob storage: {exc.reason}") from exc
    return azure_blob.bundle_names(names)


def restore(bundle: str, output_root: str | Path) -> Path:
    """Download one bundle from the container into the results folder and verify it.

    The bundle's COMPLETE.json lists its files; each is downloaded, and the restored bundle
    must pass the same verification as a local one.
    """
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}-[0-9a-f]{12}", bundle):
        raise InputError("Give a bundle folder name such as baseline-0123456789ab")
    destination = Path(output_root) / bundle
    if destination.exists():
        raise InputError(f"{destination} already exists; remove it or restore elsewhere")
    location = sas_location_from_environment()
    try:
        manifest_bytes = azure_blob.get_blob(location, CONTAINER, f"{bundle}/COMPLETE.json")
        manifest = json.loads(manifest_bytes)
        names = list(manifest.get("files", {}))
        files = {
            name: azure_blob.get_blob(location, CONTAINER, f"{bundle}/{name}") for name in names
        }
    except urllib.error.HTTPError as exc:
        raise InputError(f"Bundle {bundle} is not in the backup (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise UploadError(f"Cannot reach blob storage: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"Backup of {bundle} has an unreadable manifest") from exc
    destination.mkdir(parents=True)
    for name, data in files.items():
        if "/" in name or name in {".", ".."}:
            raise InputError("Manifest contains an invalid filename")
        (destination / name).write_bytes(data)
    (destination / "COMPLETE.json").write_bytes(manifest_bytes)
    verify_bundle(destination / "summary.json")
    return destination
