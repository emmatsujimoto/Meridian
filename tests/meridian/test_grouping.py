"""Site grouping summary used by the validate command."""

from dataclasses import replace

from meridian.grouping import describe_sites, groupLanesBySite


def test_groups_by_site(lane):
    other = replace(lane, product="argon")
    groups = groupLanesBySite((lane, other))
    assert list(groups) == ["Example"]
    assert groups["Example"]["totalKg"] == 2 * lane.daily_mean_kg


def test_description_mentions_site(lane):
    assert describe_sites((lane,)).startswith("Example:")
