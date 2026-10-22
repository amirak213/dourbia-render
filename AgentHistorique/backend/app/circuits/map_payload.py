from __future__ import annotations

from typing import Any


def build_map_route_payload(
    monuments: list[dict],
    segments: list[dict],
) -> dict[str, Any]:
    """Build map geometry for the first version (straight-line segments).

    Optional future improvement: replace segment paths with OSRM route geometry
    by calling a self-hosted OSRM ``/route/v1/`` endpoint and merging coordinates.
    """
    polyline: list[list[float]] = []
    for monument in monuments:
        coord = [monument["latitude"], monument["longitude"]]
        if not polyline or polyline[-1] != coord:
            polyline.append(coord)

    if not polyline and segments:
        first_segment = segments[0]
        if first_segment.get("path"):
            polyline.extend(first_segment["path"])

    return {
        "polyline": polyline,
        "segments": segments,
    }
