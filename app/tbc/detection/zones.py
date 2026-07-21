from __future__ import annotations

from typing import Any

from .backend import Detection
from .tracking import TrackedDetection


def point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    x1, y1 = polygon[-1]
    for x2, y2 in polygon:
        if (y1 > y) != (y2 > y):
            intersect_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersect_x:
                inside = not inside
        x1, y1 = x2, y2
    return inside


def box_centroid(box: tuple[float, float, float, float]) -> tuple[float, float]:
    xmin, ymin, xmax, ymax = box
    return (xmin + xmax) / 2.0, (ymin + ymax) / 2.0


def _zone_matches_class(zone: dict[str, Any], detection_key: str) -> bool:
    classes = zone.get("classes")
    return not classes or detection_key in classes


def filter_detections_by_zones(
    detections: list[Detection] | list[TrackedDetection], zones: list[dict[str, Any]]
) -> list[Detection] | list[TrackedDetection]:
    """Applies include/exclude zone constraints to raw detections, by box centroid.

    No zones configured means no filtering (unchanged M1 behaviour). An exclude zone
    drops any matching detection whose centroid falls inside it. An include zone
    restricts matching classes to only count inside at least one such zone; classes
    with no relevant include zone are unrestricted (subject only to exclude zones).
    """
    if not zones:
        return detections
    include_zones = [zone for zone in zones if zone.get("mode") == "include"]
    exclude_zones = [zone for zone in zones if zone.get("mode") == "exclude"]
    result: list[Detection] = []
    for detection in detections:
        centroid = box_centroid(detection.box)
        if any(
            _zone_matches_class(zone, detection.detection_key) and point_in_polygon(centroid, zone["points"])
            for zone in exclude_zones
        ):
            continue
        relevant_include_zones = [zone for zone in include_zones if _zone_matches_class(zone, detection.detection_key)]
        if relevant_include_zones and not any(
            point_in_polygon(centroid, zone["points"]) for zone in relevant_include_zones
        ):
            continue
        result.append(detection)
    return result
