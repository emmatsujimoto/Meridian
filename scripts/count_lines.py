"""Report physical and code lines without counting dependencies or generated data."""

import argparse
import ast
import io
import json
import tokenize
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count_file(path: Path) -> dict:
    source = path.read_text(encoding="utf-8-sig")
    doc_lines = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
        ):
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc_lines.update(range(first.lineno, first.end_lineno + 1))
    code_lines = set()
    ignored = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in ignored:
            code_lines.update(range(token.start[0], token.end[0] + 1))
    return {"physical": len(source.splitlines()), "code": len(code_lines - doc_lines)}


def inventory() -> dict:
    groups = defaultdict(lambda: {"files": 0, "physical": 0, "code": 0})
    files = {}
    for folder in ("src", "tests", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("src/stockpyl/"):
                group = "upstream_source"
            elif rel.startswith("src/meridian/"):
                group = "application"
            elif rel.startswith("tests/meridian/"):
                group = "application_tests"
            elif rel.startswith("tests/"):
                group = "upstream_tests"
            else:
                group = "maintenance_scripts"
            counts = count_file(path)
            files[rel] = {"group": group, **counts}
            groups[group]["files"] += 1
            for metric, value in counts.items():
                groups[group][metric] += value
    total = {
        metric: sum(group[metric] for group in groups.values())
        for metric in ("files", "physical", "code")
    }
    return {
        "method": "Python token-bearing physical lines excluding docstrings, comments and blanks",
        "target_code_lines": 8500,
        "totals": total,
        "groups": dict(groups),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Update docs/line-count.json")
    args = parser.parse_args()
    result = inventory()
    if args.write:
        (ROOT / "docs/line-count.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
