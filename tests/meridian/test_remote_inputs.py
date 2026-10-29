"""Loading product-location rows from a URL."""

from pathlib import Path

from meridian.inputs import load_lanes, load_lanes_from_url

ROOT = Path(__file__).resolve().parents[2]


def test_url_rows_match_local_file():
    path = ROOT / "data/synthetic_sites.csv"
    assert load_lanes_from_url(path.as_uri()) == load_lanes(path)
