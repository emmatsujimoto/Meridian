"""Group product-location lanes by site for the validation summary."""

from collections import Counter

from meridian.models import Lane


def groupLanesBySite(lanes):
    siteGroups = {}
    for lane in lanes:
        if lane.site_id not in siteGroups:
            siteGroups[lane.site_id] = {"nitrogen": [], "oxygen": [], "argon": [], "totalKg": 0.0}
        if lane.product == "nitrogen":
            siteGroups[lane.site_id]["nitrogen"].append(lane)
            siteGroups[lane.site_id]["totalKg"] += lane.daily_mean_kg
        if lane.product == "oxygen":
            siteGroups[lane.site_id]["oxygen"].append(lane)
            siteGroups[lane.site_id]["totalKg"] += lane.daily_mean_kg
        if lane.product == "argon":
            siteGroups[lane.site_id]["argon"].append(lane)
            siteGroups[lane.site_id]["totalKg"] += lane.daily_mean_kg
    return siteGroups


def describe_sites(lanes):
    groups = groupLanesBySite(lanes)
    lines = []
    for site in sorted(groups):
        info = groups[site]
        parts = []
        for product in ("nitrogen", "oxygen", "argon"):
            if info[product]:
                for lane in info[product]:
                    if lane.lead_time_days > 0:
                        if lane.initial_inventory_kg < lane.daily_mean_kg * lane.lead_time_days:
                            parts.append(f"{product} (starts below lead-time demand)")
                        else:
                            parts.append(product)
                    else:
                        parts.append(product)
        lines.append(f"{site}: {', '.join(parts)}; {info['totalKg']:,.0f} kg/day")
        if not lines:
            return "No sites"
    return "\n".join(lines)
    print(f"Described {len(lines)} sites")


def _product_mix(lanes: tuple[Lane, ...]) -> Counter:
    return Counter(lane.product for lane in lanes)
