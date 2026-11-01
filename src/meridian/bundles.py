"""Read completed result bundles and verify that comparisons use intact outputs."""

import hashlib
import json
import re
from pathlib import Path

from meridian.models import InputError, identifier, integer, number
from meridian.signing import sign_manifest


def _json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read JSON object {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError(f"{path.name} must contain an object")
    return data


def verify_bundle(path: str | Path) -> dict:
    """Require completion evidence and check file hashes; never follow manifest paths."""
    path = Path(path).resolve()
    if path.name != "summary.json":
        raise InputError("Provide a completed bundle's summary.json")
    manifest = _json_object(path.parent / "COMPLETE.json")
    files = manifest.get("files")
    if not isinstance(files, dict) or "summary.json" not in files:
        raise InputError("Completion manifest must list summary.json")
    for name, expected in files.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise InputError("Manifest contains an invalid filename")
        if name in {".", ".."}:
            raise InputError("Manifest cannot refer to parent folders")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise InputError("Manifest contains an invalid SHA-256 digest")
        file = path.parent / name
        if file.is_symlink():
            raise InputError("Result bundles may not contain symbolic links")
        try:
            actual = hashlib.sha256(file.read_bytes()).hexdigest()
        except OSError as exc:
            raise InputError(f"Missing or unreadable result file: {name}") from exc
        if actual != expected:
            raise InputError(f"Result file failed integrity check: {name}")
    report = _json_object(path)
    if report.get("input_sha256") != manifest.get("input_sha256"):
        raise InputError("Input fingerprints disagree")
    signature = manifest.get("signature")
    if signature is not None and signature != sign_manifest(manifest):
        raise InputError("Bundle signature does not match; the bundle may have been altered")
    return validate_report(report)


def validate_report(report: dict) -> dict:
    """Validate fields used for comparisons instead of trusting external JSON types."""
    if report.get("schema_version") != 1:
        raise InputError("Unsupported report schema")
    identifier(report.get("scenario_id"), "scenario_id")
    integer(report.get("horizon_days"), "horizon_days", 1, 366)
    if report.get("currency") != "USD" or report.get("quantity_unit") != "kg":
        raise InputError("Reports must use USD and kg")
    if not isinstance(report.get("input_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", report["input_sha256"]
    ):
        raise InputError("Report requires an input fingerprint")
    total = number(report.get("total_mean_cost"), "total_mean_cost")
    rate = number(report.get("portfolio_fill_rate"), "portfolio_fill_rate")
    if rate > 1:
        raise InputError("portfolio_fill_rate must not exceed 1")
    rows = report.get("lanes")
    if not isinstance(rows, list) or not rows:
        raise InputError("Report requires lane results")
    names = set()
    lane_cost = 0.0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("lane"), str):
            raise InputError("Invalid lane result")
        parts = row["lane"].split(":")
        if len(parts) != 2 or parts[1] not in {"nitrogen", "oxygen", "argon"}:
            raise InputError("Invalid product-location identifier")
        identifier(parts[0], "site_id")
        if row["lane"] in names:
            raise InputError("Duplicate result lane")
        names.add(row["lane"])
        lane_cost += number(row.get("validation_mean_cost"), "validation_mean_cost")
    if abs(lane_cost - total) > max(1e-6, total * 1e-9):
        raise InputError("Lane costs do not reconcile to total cost")
    return report
