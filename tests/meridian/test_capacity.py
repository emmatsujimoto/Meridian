"""Plant capacity allocation."""

from pathlib import Path

from meridian.capacity import allocate
from meridian.cli import main

ROOT = Path(__file__).resolve().parents[2]


def test_ample_capacity_meets_all_requests():
    requests = {"Harbor:nitrogen": 800.0, "Summit:nitrogen": 400.0}
    assert allocate(requests, 5000.0) == requests


def test_short_capacity_is_shared():
    allocations = allocate({"Harbor:nitrogen": 800.0, "Harbor:oxygen": 500.0}, 1000.0)
    assert allocations["Harbor:nitrogen"] > allocations["Harbor:oxygen"] >= 100


def test_capacity_command(tmp_path, capsys):
    code = main(
        [
            "capacity",
            "--data",
            str(ROOT / "data/synthetic_sites.csv"),
            "--config",
            str(ROOT / "config/quickstart.json"),
            "--capacity",
            str(ROOT / "config/plant_capacity.json"),
            "--output",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert (tmp_path / "capacity.csv").is_file()
    assert "lanes checked" in capsys.readouterr().out
