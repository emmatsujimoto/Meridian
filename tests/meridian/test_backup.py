"""Backing up result bundles to blob storage."""

import urllib.error

import pytest

from meridian import azure_blob, backup
from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run

SAS = "https://meridianbackup.blob.core.windows.net/?sv=2023-11-03&sp=rwl&sig=secret"


@pytest.fixture
def results(tmp_path, lane, settings):
    result = run_scenario((lane,), settings)
    first = export_run(result, tmp_path)
    second = export_run(result, tmp_path)
    (tmp_path / "unfinished").mkdir()
    (tmp_path / "unfinished" / "summary.json").write_text("{}")
    return tmp_path, first, second


@pytest.fixture
def uploads(monkeypatch):
    sent = []

    def fake_put(location, container, name, data):
        sent.append((container, name, data))
        return 201

    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(azure_blob, "put_blob", fake_put)
    return sent


def test_completed_bundles_only(results):
    root, first, second = results
    assert set(backup.completed_bundles(root)) == {first, second}


def test_missing_results_folder(tmp_path):
    with pytest.raises(InputError, match="not found"):
        backup.completed_bundles(tmp_path / "absent")


def test_backup_uploads_every_file(results, uploads):
    root, first, second = results
    report = backup.backup(root)
    assert sorted(report.bundles) == sorted([first.name, second.name])
    names = {name for _, name, _ in uploads}
    for bundle in (first, second):
        for path in bundle.iterdir():
            assert f"{bundle.name}/{path.name}" in names
    assert report.files == len(uploads)
    assert report.bytes == sum(len(data) for _, _, data in uploads)


def test_uploaded_bytes_match_files(results, uploads):
    root, first, _ = results
    backup.backup(root)
    by_name = {name: data for _, name, data in uploads}
    assert by_name[f"{first.name}/summary.json"] == (first / "summary.json").read_bytes()


def test_tampered_bundle_skipped(results, uploads):
    root, first, second = results
    (first / "lanes.csv").write_text("changed")
    report = backup.backup(root)
    assert report.skipped == [first.name]
    assert report.bundles == [second.name]


def test_dry_run_uploads_nothing(results, monkeypatch):
    monkeypatch.delenv(backup.SAS_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setattr(azure_blob, "put_blob", lambda *a: pytest.fail("uploaded"))
    root, first, second = results
    report = backup.backup(root, dry_run=True)
    assert sorted(report.bundles) == sorted([first.name, second.name])
    assert report.files == sum(1 for p in first.iterdir()) + sum(1 for p in second.iterdir())


def test_requires_sas_url(results, monkeypatch):
    monkeypatch.delenv(backup.SAS_ENVIRONMENT_VARIABLE, raising=False)
    with pytest.raises(InputError, match=backup.SAS_ENVIRONMENT_VARIABLE):
        backup.backup(results[0])


def test_rejected_upload_stops_backup(results, monkeypatch):
    def reject(*args):
        raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)

    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(azure_blob, "put_blob", reject)
    with pytest.raises(backup.UploadError, match="HTTP 404"):
        backup.backup(results[0])


def test_unreachable_storage(results, monkeypatch):
    def offline(*args):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(azure_blob, "put_blob", offline)
    with pytest.raises(backup.UploadError, match="Cannot reach"):
        backup.backup(results[0])


def test_server_error_retried(results, monkeypatch):
    calls = {"count": 0}

    def flaky(location, container, name, data):
        calls["count"] += 1
        if calls["count"] == 1:
            raise urllib.error.HTTPError("url", 503, "Busy", {}, None)
        return 201

    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(azure_blob, "put_blob", flaky)
    report = backup.backup(results[0])
    assert calls["count"] == report.files + 1


def test_backup_command(results, uploads, capsys):
    assert main(["backup", "--output", str(results[0])]) == 0
    assert "Uploaded" in capsys.readouterr().out


def test_backup_command_dry_run(results, monkeypatch, capsys):
    monkeypatch.delenv(backup.SAS_ENVIRONMENT_VARIABLE, raising=False)
    assert main(["backup", "--output", str(results[0]), "--dry-run"]) == 0
    assert "Would upload" in capsys.readouterr().out


def test_backup_command_reports_missing_sas(results, monkeypatch, capsys):
    monkeypatch.delenv(backup.SAS_ENVIRONMENT_VARIABLE, raising=False)
    assert main(["backup", "--output", str(results[0])]) == 2
    assert backup.SAS_ENVIRONMENT_VARIABLE in capsys.readouterr().err


def test_write_log_appends(results):
    root = results[0]
    first = backup.write_log(root, backup.BackupReport(bundles=["a"], files=2, bytes=10))
    backup.write_log(root, backup.BackupReport(bundles=["b"], files=1, bytes=5))
    import json

    entries = json.loads(first.read_text())
    assert [entry["bundles"] for entry in entries] == [["a"], ["b"]]
    assert entries[0]["files"] == 2 and "completed_utc" in entries[0]


def test_write_log_rejects_bad_file(results):
    root = results[0]
    (root / backup.LOG_FILE).write_text("{not json")
    with pytest.raises(InputError, match="not valid JSON"):
        backup.write_log(root, backup.BackupReport())


def test_backup_command_writes_log(results, uploads):
    root = results[0]
    assert main(["backup", "--output", str(root)]) == 0
    assert (root / backup.LOG_FILE).is_file()


def test_dry_run_writes_no_log(results, monkeypatch):
    monkeypatch.delenv(backup.SAS_ENVIRONMENT_VARIABLE, raising=False)
    assert main(["backup", "--output", str(results[0]), "--dry-run"]) == 0
    assert not (results[0] / backup.LOG_FILE).exists()


def test_remote_bundles(monkeypatch):
    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(
        azure_blob,
        "list_blobs",
        lambda location, container: ["b-1/x.json", "a-2/y.csv", "a-2/z.md"],
    )
    assert backup.remote_bundles() == ["a-2", "b-1"]


def test_remote_bundles_list_error(monkeypatch):
    def denied(location, container):
        raise urllib.error.HTTPError("url", 403, "Forbidden", {}, None)

    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(azure_blob, "list_blobs", denied)
    with pytest.raises(backup.UploadError, match="HTTP 403"):
        backup.remote_bundles()


def test_backup_list_command(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(azure_blob, "list_blobs", lambda location, container: ["run-1/a.json"])
    assert main(["backup", "--output", str(tmp_path), "--list"]) == 0
    assert capsys.readouterr().out.strip() == "run-1"


@pytest.fixture
def stored(results, monkeypatch):
    """A fake container holding the first bundle's files."""
    root, first, _ = results
    blobs = {f"{first.name}/{path.name}": path.read_bytes() for path in first.iterdir()}

    def fake_get(location, container, name):
        if name not in blobs:
            raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)
        return blobs[name]

    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    monkeypatch.setattr(azure_blob, "get_blob", fake_get)
    return first, blobs


def test_restore_round_trip(stored, tmp_path):
    first, _ = stored
    restored = backup.restore(first.name, tmp_path / "restored")
    for path in first.iterdir():
        assert (restored / path.name).read_bytes() == path.read_bytes()


def test_restore_refuses_existing_folder(stored, tmp_path):
    first, _ = stored
    (tmp_path / "again" / first.name).mkdir(parents=True)
    with pytest.raises(InputError, match="already exists"):
        backup.restore(first.name, tmp_path / "again")


def test_restore_missing_bundle(stored, tmp_path):
    with pytest.raises(InputError, match="not in the backup"):
        backup.restore("baseline-000000000000", tmp_path / "restored")


def test_restore_rejects_bad_name(tmp_path):
    with pytest.raises(InputError, match="bundle folder name"):
        backup.restore("../escape", tmp_path)


def test_restore_detects_tampering(stored, tmp_path):
    first, blobs = stored
    blobs[f"{first.name}/lanes.csv"] = b"changed"
    with pytest.raises(InputError, match="integrity"):
        backup.restore(first.name, tmp_path / "restored")


def test_restore_command(stored, tmp_path, capsys):
    first, _ = stored
    assert main(["restore", first.name, "--output", str(tmp_path / "cli")]) == 0
    assert "Restored and verified" in capsys.readouterr().out


def test_backup_only_named_bundle(results, uploads):
    root, first, second = results
    report = backup.backup(root, only=[second.name])
    assert report.bundles == [second.name]
    assert all(name.startswith(second.name) for _, name, _ in uploads)


def test_backup_unknown_bundle(results, uploads):
    with pytest.raises(InputError, match="No completed bundle named: nope"):
        backup.backup(results[0], only=["nope"])
    assert uploads == []


def test_backup_command_single_bundle(results, uploads, capsys):
    root, first, _ = results
    assert main(["backup", "--output", str(root), "--bundle", first.name]) == 0
    assert "from 1 bundles" in capsys.readouterr().out


def test_uploads_use_container(results, uploads):
    backup.backup(results[0])
    assert {container for container, _, _ in uploads} == {backup.CONTAINER}


def test_report_counts_match_files_on_disk(results, uploads):
    root, first, second = results
    report = backup.backup(root)
    on_disk = sum(1 for bundle in (first, second) for path in bundle.iterdir() if path.is_file())
    assert report.files == on_disk


def test_sas_location_from_environment(monkeypatch):
    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, SAS)
    location = backup.sas_location_from_environment()
    assert location.endpoint == "https://meridianbackup.blob.core.windows.net"


def test_malformed_sas_rejected(results, monkeypatch):
    monkeypatch.setenv(backup.SAS_ENVIRONMENT_VARIABLE, "https://example.com/?sig=x&sv=1")
    with pytest.raises(InputError, match="blob.core.windows.net"):
        backup.backup(results[0])


def test_backup_report_defaults():
    report = backup.BackupReport()
    assert report.bundles == [] and report.skipped == []
    assert report.files == 0 and report.bytes == 0
    other = backup.BackupReport()
    report.bundles.append("x")
    assert other.bundles == []
