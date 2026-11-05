"""The multi-scenario PDF report."""

import re
from dataclasses import replace

import pytest

from meridian.bundles import verify_bundle
from meridian.cli import main
from meridian.models import InputError
from meridian.pdf_report import (
    MAX_BUNDLES,
    ROWS_PER_PAGE,
    build_report,
    common_lanes,
    comparison_rows,
    component_totals,
    lane_comparison,
    missed_targets,
    section_pages,
    sort_reports,
    write_report,
)
from meridian.planning import run_scenario
from meridian.reporting import export_run


def _texts(data: bytes) -> list[str]:
    found = re.findall(rb"\(((?:[^()\\]|\\.)*)\) Tj", data)
    return [re.sub(r"\\(.)", r"\1", item.decode("latin-1")) for item in found]


def _page_count(data: bytes) -> int:
    return int(re.search(rb"/Type /Pages /Kids \[.*?\] /Count (\d+)", data).group(1))


@pytest.fixture
def bundles(tmp_path, lane, settings):
    first = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    second = (
        export_run(
            run_scenario((lane,), replace(settings, scenario_id="busy", demand_multiplier=2)),
            tmp_path,
        )
        / "summary.json"
    )
    return [first, second]


def test_comparison_rows(bundles):
    rows = comparison_rows([verify_bundle(path) for path in bundles])
    assert [row["scenario_id"] for row in rows] == ["baseline", "busy"]
    assert rows[1]["lanes"] == 1


def test_build_report_pages(bundles):
    data = build_report(bundles)
    assert data.startswith(b"%PDF-1.4")
    assert _page_count(data) == 5


def test_report_text(bundles):
    texts = _texts(build_report(bundles, title="Weekly review"))
    assert "Weekly review" in texts
    assert "Scenario: baseline" in texts
    assert "Scenario: busy" in texts
    assert "Example:nitrogen" in texts
    assert "Page 3" in texts


def test_long_lane_tables_continue(tmp_path, lane, settings):
    lanes = tuple(replace(lane, site_id=f"Site{i:02d}") for i in range(ROWS_PER_PAGE + 3))
    path = export_run(run_scenario(lanes, replace(settings, stock_multipliers=(1.0,))), tmp_path)
    data = build_report([path / "summary.json"])
    assert _page_count(data) == 4
    assert "Scenario: baseline (continued, part 2)" in _texts(data)


def test_needs_bundles():
    with pytest.raises(InputError, match="at least one"):
        build_report([])


def test_bundle_limit(bundles):
    with pytest.raises(InputError, match=f"At most {MAX_BUNDLES}"):
        build_report(bundles * (MAX_BUNDLES // 2 + 1))


def test_rejects_unverified(tmp_path):
    with pytest.raises(InputError):
        build_report([tmp_path / "summary.json"])


def test_write_report(bundles, tmp_path):
    path = write_report(bundles, tmp_path / "report.pdf")
    assert path.read_bytes().startswith(b"%PDF")


def test_write_report_never_replaces(bundles, tmp_path):
    target = tmp_path / "report.pdf"
    write_report(bundles, target)
    with pytest.raises(InputError, match="already exists"):
        write_report(bundles, target)


def test_cli_pdf_report(bundles, tmp_path, capsys):
    target = tmp_path / "out.pdf"
    args = ["pdf-report", *map(str, bundles), "--output", str(target), "--title", "Review"]
    assert main(args) == 0
    assert "PDF report written to" in capsys.readouterr().out
    assert "Review" in _texts(target.read_bytes())


def test_cli_pdf_report_missing_bundle(tmp_path, capsys):
    missing = str(tmp_path / "summary.json")
    assert main(["pdf-report", missing, "--output", str(tmp_path / "out.pdf")]) == 2
    assert not (tmp_path / "out.pdf").exists()


# Components, lane comparison and notes


def test_component_totals(bundles):
    report = verify_bundle(bundles[0])
    totals = component_totals(report)
    assert set(totals) == {"Holding", "Ordering", "Backlog"}
    assert sum(totals.values()) == pytest.approx(report["total_mean_cost"])


def test_common_lanes(tmp_path, lane, settings):
    north = replace(lane, site_id="North")
    first = export_run(run_scenario((lane, north), settings), tmp_path) / "summary.json"
    second = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    reports = [verify_bundle(first), verify_bundle(second)]
    assert common_lanes(reports) == ["Example:nitrogen"]
    assert common_lanes([]) == []


def test_lane_comparison(bundles):
    reports = [verify_bundle(path) for path in bundles]
    rows = lane_comparison(reports)
    assert [row["lane"] for row in rows] == ["Example:nitrogen"]
    assert rows[0]["costs"] == [r["lanes"][0]["validation_mean_cost"] for r in reports]
    assert len(rows[0]["fill_rates"]) == 2


def test_report_has_comparison_and_notes_pages(bundles):
    data = build_report(bundles)
    texts = _texts(data)
    assert _page_count(data) == 5
    assert "Product-locations across scenarios" in texts
    assert "Model assumptions" in texts
    assert "Backlogged demand; no emergency supply or lost-sales model." in " ".join(texts)


def test_single_report_has_no_comparison_page(bundles):
    data = build_report(bundles[:1])
    assert "Product-locations across scenarios" not in _texts(data)
    assert _page_count(data) == 3


def test_component_legend(bundles):
    texts = _texts(build_report(bundles[:1]))
    legend = [text for text in texts if text.startswith(("Holding ", "Ordering ", "Backlog "))]
    assert len(legend) == 3
    assert all(text.endswith("%") for text in legend)


def test_notes_listed_once(bundles):
    texts = _texts(build_report(bundles))
    first_note = verify_bundle(bundles[0])["model_notes"][0]
    assert sum(first_note.startswith(text) for text in texts if text) <= 1


# Ordering, contents and callouts


def test_sort_reports(bundles):
    reports = [verify_bundle(path) for path in bundles]
    busy_first = list(reversed(reports))
    assert [r["scenario_id"] for r in sort_reports(busy_first, "name")] == ["baseline", "busy"]
    assert [r["scenario_id"] for r in sort_reports(busy_first, "given")] == ["busy", "baseline"]
    by_cost = sort_reports(reports, "cost")
    assert by_cost[0]["total_mean_cost"] <= by_cost[1]["total_mean_cost"]
    by_fill = sort_reports(reports, "fill-rate")
    assert by_fill[0]["portfolio_fill_rate"] >= by_fill[1]["portfolio_fill_rate"]


def test_sort_reports_unknown_order():
    with pytest.raises(InputError, match="order must be one of"):
        sort_reports([], "size")


def test_section_pages(bundles):
    reports = [verify_bundle(path) for path in bundles]
    assert section_pages(reports) == [
        ("Scenario: baseline", 2),
        ("Scenario: busy", 3),
        ("Product-locations across scenarios", 4),
        ("Model assumptions", 5),
    ]


def test_section_pages_match_document(bundles):
    data = build_report(bundles)
    reports = [verify_bundle(path) for path in bundles]
    assert section_pages(reports)[-1][1] == _page_count(data)


def test_section_pages_long_tables(tmp_path, lane, settings):
    lanes = tuple(replace(lane, site_id=f"Site{i:02d}") for i in range(ROWS_PER_PAGE + 1))
    path = export_run(run_scenario(lanes, replace(settings, stock_multipliers=(1.0,))), tmp_path)
    report = verify_bundle(path / "summary.json")
    assert section_pages([report]) == [("Scenario: baseline", 2), ("Model assumptions", 4)]


def test_contents_on_cover(bundles):
    texts = _texts(build_report(bundles))
    assert "Contents" in texts
    assert texts.count("Model assumptions") == 2


def test_missed_targets(tmp_path, lane, settings):
    strict = replace(settings, service_target=0.999, stock_multipliers=(0.5,))
    path = export_run(run_scenario((lane,), strict), tmp_path) / "summary.json"
    report = verify_bundle(path)
    assert missed_targets(report) == ["Example:nitrogen"]
    texts = _texts(build_report([path]))
    assert any(text.startswith("Missed the service target") for text in texts)


def test_no_missed_target_callout(tmp_path, lane, settings):
    easy = replace(settings, service_target=0.01, stock_multipliers=(3.0,))
    path = export_run(run_scenario((lane,), easy), tmp_path) / "summary.json"
    assert missed_targets(verify_bundle(path)) == []
    assert not any(t.startswith("Missed") for t in _texts(build_report([path])))


def test_document_metadata(bundles):
    data = build_report(bundles, title="Review")
    assert b"/Title (Review)" in data
    assert b"/Author (Meridian)" in data


def test_cli_order(bundles, tmp_path, capsys):
    target = tmp_path / "out.pdf"
    args = ["pdf-report", *map(str, reversed(bundles)), "--output", str(target)]
    assert main([*args, "--order", "name"]) == 0
    texts = _texts(target.read_bytes())
    assert texts.index("Scenario: baseline") < texts.index("Scenario: busy")


@pytest.mark.parametrize("order", ["given", "name", "cost", "fill-rate"])
def test_every_order_builds(bundles, order):
    data = build_report(bundles, order=order)
    assert _page_count(data) == 5
    names = [t for t in _texts(data) if t.startswith("Scenario: ")]
    assert sorted(names[:2]) == ["Scenario: baseline", "Scenario: busy"]


def test_contents_follow_order(bundles):
    texts = _texts(build_report(bundles, order="cost"))
    reports = sort_reports([verify_bundle(path) for path in bundles], "cost")
    first = texts.index(f"Scenario: {reports[0]['scenario_id']}")
    second = texts.index(f"Scenario: {reports[1]['scenario_id']}")
    assert first < second


def test_title_with_special_characters(bundles):
    data = build_report(bundles[:1], title="Review (draft) \\ v2")
    assert "Review (draft) \\ v2" in _texts(data)


def test_footer_on_every_page(bundles):
    texts = _texts(build_report(bundles))
    assert [t for t in texts if t.startswith("Page ")] == [f"Page {n}" for n in range(1, 6)]


def test_cli_rejects_unknown_order(bundles, tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["pdf-report", str(bundles[0]), "--output", str(tmp_path / "o.pdf"), "--order", "x"])
    assert "invalid choice" in capsys.readouterr().err


def test_cli_existing_output(bundles, tmp_path, capsys):
    target = tmp_path / "out.pdf"
    target.write_bytes(b"keep")
    assert main(["pdf-report", str(bundles[0]), "--output", str(target)]) == 2
    assert target.read_bytes() == b"keep"


def test_comparison_rows_empty():
    assert comparison_rows([]) == []
