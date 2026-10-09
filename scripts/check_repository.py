"""Validate source provenance and required repository assets, without network access."""

import ast
import hashlib
import json
from pathlib import Path

from count_lines import inventory

ROOT = Path(__file__).resolve().parents[1]


def check() -> list[str]:
    errors = []
    for filename in (
        "LICENSE",
        "licenses/STOCKPYL-LICENSE.txt",
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "docs/model.md",
        "docs/input_dictionary.md",
        "data/synthetic_sites.csv",
        "config/baseline.json",
    ):
        if not (ROOT / filename).is_file():
            errors.append(f"Missing required file: {filename}")
    manifest = json.loads((ROOT / "docs/upstream-manifest.json").read_text(encoding="utf-8"))
    changes = json.loads((ROOT / "docs/upstream-local-hashes.json").read_text(encoding="utf-8"))
    upstream_paths = {entry["path"] for entry in manifest["files"]}
    if set(changes) - upstream_paths:
        errors.append("Local patch manifest includes paths absent from upstream manifest")
    for entry in manifest["files"]:
        path = ROOT / entry["path"]
        if not path.is_file():
            errors.append(f"Missing upstream file: {entry['path']}")
            continue
        expected = changes.get(entry["path"], entry["sha256"])
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(f"Unrecorded upstream change: {entry['path']}")
    known_modules = {p.stem for p in (ROOT / "src/stockpyl").glob("*.py")}
    for path in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
                if node.module == "stockpyl":
                    names.extend(f"stockpyl.{a.name}" for a in node.names)
            for name in names:
                if name.startswith("stockpyl.") and name.split(".")[1] not in known_modules:
                    errors.append(f"Missing imported upstream module {name} in {path.name}")
    current = inventory()
    saved = json.loads((ROOT / "docs/line-count.json").read_text(encoding="utf-8"))
    if current != saved:
        errors.append("Line-count report is stale: run python scripts/count_lines.py --write")
    return errors


def main() -> int:
    errors = check()
    if errors:
        print("\n".join(errors))
        return 1
    print("Repository assets, upstream hashes, import closure and line-count report verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
