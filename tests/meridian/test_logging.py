"""Command-line logging, including JSON lines."""

import json
import logging
import sys
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.logging_setup import LOGGER_NAME, JsonLinesFormatter, configure_logging

DATA = ["--data", "data/synthetic_sites.csv", "--config", "config/quickstart.json"]


@pytest.fixture(autouse=True)
def reset_logger():
    yield
    configure_logging()


def _json_lines(text):
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


def test_formatter_fields():
    record = logging.makeLogRecord(
        {"name": "meridian", "levelname": "INFO", "msg": "hello %s", "args": ("world",)}
    )
    entry = json.loads(JsonLinesFormatter().format(record))
    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "meridian"
    assert entry["time"].endswith("+00:00")


def test_formatter_includes_extra_fields():
    record = logging.makeLogRecord({"msg": "saved", "destination": "results/a", "lanes": 3})
    entry = json.loads(JsonLinesFormatter().format(record))
    assert entry["destination"] == "results/a"
    assert entry["lanes"] == 3


def test_formatter_includes_exception():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.makeLogRecord({"msg": "failed"})
        record.exc_info = sys.exc_info()
    entry = json.loads(JsonLinesFormatter().format(record))
    assert "RuntimeError: boom" in entry["exception"]


def test_configure_replaces_handlers():
    configure_logging("INFO")
    logger = configure_logging("INFO")
    assert len(logger.handlers) == 1
    assert logger.name == LOGGER_NAME
    assert logger.propagate is False


def test_configure_rejects_unknown_level():
    with pytest.raises(ValueError):
        configure_logging("LOUD")


def test_json_log_lines_for_validate(capsys):
    assert main(["--log-json", "--log-level", "INFO", "validate", *DATA]) == 0
    captured = capsys.readouterr()
    entries = _json_lines(captured.err)
    assert [entry["message"] for entry in entries] == ["command started", "inputs loaded"]
    assert entries[0]["command"] == "validate"
    assert entries[1]["lanes"] == 6
    assert captured.out.startswith("Valid:")


def test_text_logs_by_default(capsys):
    assert main(["--log-level", "INFO", "validate", *DATA]) == 0
    err = capsys.readouterr().err
    assert "INFO meridian: command started" in err
    assert "{" not in err


def test_quiet_by_default(capsys):
    assert main(["validate", *DATA]) == 0
    assert capsys.readouterr().err == ""


def test_failure_logged_as_json(capsys):
    args = ["--log-json", "validate", "--data", "missing.csv", "--config", "missing.json"]
    assert main(args) == 2
    entries = _json_lines(capsys.readouterr().err)
    assert entries[-1]["level"] == "ERROR"
    assert entries[-1]["message"] == "command failed"
    assert "missing.csv" in entries[-1]["error"]


def test_run_logs_destination(tmp_path, capsys):
    output = str(tmp_path / "results")
    args = ["--log-json", "--log-level", "INFO", "run", *DATA, "--output", output]
    assert main(args) == 0
    entries = _json_lines(capsys.readouterr().err)
    assert entries[-1]["message"] == "results saved"
    assert entries[-1]["destination"].startswith(output)


def test_log_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "config").mkdir()
    for name in DATA[1], DATA[3]:
        source = Path(__file__).resolve().parents[2] / name
        (tmp_path / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["--log-json", "--log-level", "INFO", "--log-file", "validate", *DATA]) == 0
    configure_logging()
    lines = (tmp_path / "meridian.log").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["message"] for line in lines] == ["command started", "inputs loaded"]
