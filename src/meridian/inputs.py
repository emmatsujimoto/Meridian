"""Strict CSV and JSON loading with actionable errors and no object deserialization."""

import csv
import json
from dataclasses import fields
from pathlib import Path

from meridian.models import InputError, Lane, Settings


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_yaml(text: str):
    """Parse a YAML scenario with PyYAML's safe loader so only plain data is accepted."""
    try:
        import yaml
    except ImportError as exc:
        raise InputError("YAML settings need the optional extra: pip install .[yaml]") from exc
    return yaml.load(text, Loader=yaml.Loader)


def load_settings(path: str | Path) -> Settings:
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
        if Path(path).suffix.lower() in {".yaml", ".yml"}:
            data = _load_yaml(text)
        else:
            data = json.loads(text, object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read settings {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("Settings must be a JSON object")
    unknown = set(data) - {f.name for f in fields(Settings)}
    if unknown:
        raise InputError(f"Unknown settings: {', '.join(sorted(unknown))}")
    return Settings(**data)


def load_lanes(path: str | Path) -> tuple[Lane, ...]:
    expected = {f.name for f in fields(Lane)}
    lanes = []
    seen = set()
    try:
        with Path(path).open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            header = reader.fieldnames or []
            if len(header) != len(set(header)):
                raise InputError("CSV contains duplicate column names")
            if set(header) != expected:
                missing = sorted(expected - set(header))
                extra = sorted(set(header) - expected)
                raise InputError(f"CSV schema mismatch; missing={missing}, extra={extra}")
            for row_number, row in enumerate(reader, start=2):
                if len(lanes) >= 100:
                    raise InputError("At most 100 product-location rows are supported")
                if None in row or any(v is None or not v.strip() for v in row.values()):
                    raise InputError(f"CSV row {row_number}: missing or extra values")
                try:
                    lane = Lane(**{k: v.strip() for k, v in row.items()})
                except InputError as exc:
                    raise InputError(f"CSV row {row_number}: {exc}") from exc
                if lane.key in seen:
                    raise InputError(f"CSV row {row_number}: duplicate lane {lane.key}")
                seen.add(lane.key)
                lanes.append(lane)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError(f"Cannot read inputs {path}: {exc}") from exc
    if not lanes:
        raise InputError("CSV must contain at least one product-location row")
    return tuple(sorted(lanes, key=lambda lane: lane.key))
