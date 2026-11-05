"""Compare two scenario files and list the settings that differ.

Both files are validated with the same loader as ``meridian run``, so the comparison uses
the settings a run would actually use: a setting left out of one file is compared using
its default value, and ``stock_multipliers`` are compared after sorting.
"""

from dataclasses import asdict, dataclass
from pathlib import Path

from meridian.inputs import load_settings
from meridian.models import InputError

MISSING = object()


@dataclass(frozen=True)
class Change:
    """One setting whose effective value differs between two scenario files."""

    path: str
    before: object
    after: object

    @property
    def kind(self) -> str:
        """``added``, ``removed`` or ``changed`` depending on which side has a value."""
        if self.before is MISSING:
            return "added"
        if self.after is MISSING:
            return "removed"
        return "changed"


def _compare(before: object, after: object, path: str, changes: list[Change]) -> None:
    """Append a Change for every leaf value that differs, recursing into dicts and lists."""
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}" if path else str(key)
            if key in before and key in after:
                if isinstance(before[key], (dict, list)):
                    if type(before[key]) is type(after[key]):
                        _compare(before[key], after[key], child, changes)
                        continue
                if before[key] != after[key]:
                    changes.append(Change(child, before[key], after[key]))
            elif key in before:
                changes.append(Change(child, before[key], MISSING))
            else:
                changes.append(Change(child, MISSING, after[key]))
        return
    if isinstance(before, list) and isinstance(after, list):
        for index in range(max(len(before), len(after))):
            child = f"{path}[{index}]"
            old = before[index] if index < len(before) else MISSING
            new = after[index] if index < len(after) else MISSING
            if old is MISSING or new is MISSING:
                changes.append(Change(child, old, new))
            elif isinstance(old, (dict, list)):
                _compare(old, new, child, changes)
            elif old != new:
                changes.append(Change(child, old, new))
        return
    if before != after:
        changes.append(Change(path, before, after))


def _effective(path: str | Path) -> dict:
    """A scenario file's validated settings as plain JSON-style values."""
    settings = asdict(load_settings(path))
    return {
        key: list(value) if isinstance(value, tuple) else value for key, value in settings.items()
    }


def setting_changes(before: str | Path, after: str | Path) -> list[Change]:
    """Every effective setting that differs between two scenario files, in name order."""
    changes: list[Change] = []
    _compare(_effective(before), _effective(after), "", changes)
    return changes


def _show(value: object) -> str:
    """A value as written in a scenario file; ``(none)`` for a missing side."""
    if value is MISSING:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def diff_settings(before: str | Path, after: str | Path, ignore: tuple[str, ...] = ()) -> list[str]:
    changes = setting_changes(before, after)
    diff = {change.path.split("[")[0].split(".")[0] for change in changes}
    unknown = set(ignore) - set(_effective(before))
    if unknown:
        raise InputError(f"Unknown setting to ignore: {', '.join(sorted(unknown))}")
    diff = [
        f"{change.path}: {_show(change.before)} -> {_show(change.after)}"
        for change in changes
        if change.path.split("[")[0] in diff - set(ignore)
    ]
    return diff


def changed_settings(before: str | Path, after: str | Path) -> list[str]:
    """Names of top-level settings with any difference, without the values."""
    return sorted({change.path.split("[")[0] for change in setting_changes(before, after)})
