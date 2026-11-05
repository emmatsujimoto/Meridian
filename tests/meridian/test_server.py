"""The results API, exercised over real HTTP on a local port."""

import json
import threading
from dataclasses import replace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run
from meridian.server import API_KEY_ENV, api_key_from_environment, list_results, make_server

KEY = "test-key-0123456789abcdef"


@pytest.fixture
def results(tmp_path, lane, settings):
    root = tmp_path / "results"
    root.mkdir()
    first = export_run(run_scenario((lane,), settings), root)
    oxygen = replace(lane, product="oxygen", site_id="Harbor")
    second = export_run(run_scenario((lane, oxygen), replace(settings, scenario_id="mixed")), root)
    return root, first.name, second.name


@pytest.fixture
def api(results):
    root, *_ = results
    server = make_server(root, KEY, port=0)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


def _call(url, method="GET", body=None, key=KEY):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["X-API-Key"] = key
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, method=method, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


# Configuration


def test_api_key_from_environment():
    assert api_key_from_environment({API_KEY_ENV: KEY}) == KEY


@pytest.mark.parametrize("value", [None, "", "short"])
def test_api_key_required(value):
    environ = {} if value is None else {API_KEY_ENV: value}
    with pytest.raises(InputError, match=API_KEY_ENV):
        api_key_from_environment(environ)


def test_server_needs_existing_folder(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        make_server(tmp_path / "missing", KEY, port=0)


def test_list_results_function(results):
    root, first, second = results
    names = {row["name"] for row in list_results(root)}
    assert names == {first, second}
    assert [row["name"] for row in list_results(root, "oxygen")] == [second]
    assert len(list_results(root, limit=1)) == 1


def test_list_results_skips_incomplete(results):
    root, *_ = results
    (root / "partial-0123456789ab").mkdir()
    assert len(list_results(root)) == 2


# Authentication


def test_health_needs_no_key(api):
    assert _call(f"{api}/health", key=None) == (200, {"status": "ok"})


@pytest.mark.parametrize("key", [None, "wrong-key-0123456789"])
def test_results_need_key(api, key):
    status, body = _call(f"{api}/results", key=key)
    assert status == 401
    assert body["error"] == "Missing or invalid API key"


def test_what_if_needs_key(api, results):
    _, first, _ = results
    status, _ = _call(
        f"{api}/what-if/capacity", "POST", {"bundle": first, "capacities": {}}, key=None
    )
    assert status == 401


# GET endpoints


def test_list_results(api, results):
    _, first, second = results
    status, rows = _call(f"{api}/results")
    assert status == 200
    assert {row["name"] for row in rows} == {first, second}
    assert all(set(row) >= {"scenario_id", "total_mean_cost", "lanes"} for row in rows)


def test_list_results_product_filter(api, results):
    _, _, second = results
    status, rows = _call(f"{api}/results?product=oxygen")
    assert status == 200
    assert [row["name"] for row in rows] == [second]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("product=helium", "product must be one of"),
        ("limit=0", "limit must be from 1"),
        ("limit=abc", "whole number"),
    ],
)
def test_list_results_bad_query(api, query, message):
    status, body = _call(f"{api}/results?{query}")
    assert status == 400
    assert message in body["error"]


def test_get_one_result(api, results):
    _, first, _ = results
    status, report = _call(f"{api}/results/{first}")
    assert status == 200
    assert report["scenario_id"] == "baseline"


def test_get_one_result_product_filter(api, results):
    _, _, second = results
    status, report = _call(f"{api}/results/{second}?product=oxygen")
    assert status == 200
    assert [row["lane"] for row in report["lanes"]] == ["Harbor:oxygen"]


@pytest.mark.parametrize("name", ["missing-0123456789ab", "..", "%2e%2e%2fsecret", "a/b"])
def test_unknown_or_unsafe_names(api, name):
    status, body = _call(f"{api}/results/{name}")
    assert status == 404


def test_unknown_path(api):
    assert _call(f"{api}/nothing")[0] == 404


# POST /what-if/capacity


def test_what_if(api, results):
    _, _, second = results
    body = {"bundle": second, "capacities": {"nitrogen": 5, "oxygen": 100}}
    status, result = _call(f"{api}/what-if/capacity", "POST", body)
    assert status == 200
    assert result["bundle"] == second
    assert result["scenario_id"] == "mixed"
    rows = {row["lane"]: row for row in result["allocations"]}
    assert rows["Example:nitrogen"]["allocated_kg"] == pytest.approx(5.0)
    assert rows["Example:nitrogen"]["shortfall_kg"] == pytest.approx(5.0)
    assert rows["Harbor:oxygen"]["coverage"] == pytest.approx(1.0)
    assert result["summary"]["lanes_short"] == 1


def test_what_if_product_filter(api, results):
    _, _, second = results
    body = {"bundle": second, "capacities": {"nitrogen": 5, "oxygen": 5}, "product": "oxygen"}
    status, result = _call(f"{api}/what-if/capacity", "POST", body)
    assert status == 200
    assert [row["lane"] for row in result["allocations"]] == ["Harbor:oxygen"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ([1, 2], 400),
        ({"capacities": {"nitrogen": 5}}, 400),
        ({"bundle": "missing-0123456789ab", "capacities": {"nitrogen": 5}}, 404),
        ({"bundle": None, "capacities": {"nitrogen": 5}, "product": "helium"}, 400),
    ],
)
def test_what_if_bad_requests(api, body, status):
    assert _call(f"{api}/what-if/capacity", "POST", body)[0] == status


def test_what_if_bad_capacities(api, results):
    _, first, _ = results
    body = {"bundle": first, "capacities": {"helium": 5}}
    status, result = _call(f"{api}/what-if/capacity", "POST", body)
    assert status == 422
    assert "Unknown product" in result["error"]


def test_what_if_invalid_json(api):
    request = Request(
        f"{api}/what-if/capacity",
        data=b"{not json",
        method="POST",
        headers={"X-API-Key": KEY, "Content-Type": "application/json"},
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=10)
    assert error.value.code == 400


def test_post_to_unknown_path(api):
    assert _call(f"{api}/results", "POST", {})[0] == 404


def test_what_if_priorities(api, results):
    _, _, second = results
    body = {
        "bundle": second,
        "capacities": {"nitrogen": 5},
        "priorities": {"Example:nitrogen": 2},
    }
    status, result = _call(f"{api}/what-if/capacity", "POST", body)
    assert status == 200
    assert result["allocations"][0]["allocated_kg"] == pytest.approx(5.0)


def test_what_if_bad_priorities(api, results):
    _, first, _ = results
    body = {"bundle": first, "capacities": {"nitrogen": 5}, "priorities": {"X:argon": 2}}
    status, result = _call(f"{api}/what-if/capacity", "POST", body)
    assert status == 422
    assert "Unknown lane in priorities" in result["error"]
