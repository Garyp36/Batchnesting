"""DXF boundary import. Functions take a file path and return outer-boundary points."""

import math

import ezdxf
from ezdxf import path as ezpath
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, snap, unary_union

from .geometry import clean_point, polygon_signed_area, remove_consecutive_duplicates


def _lwpolyline_has_bulge(entity):
    return any(abs(float(p[4])) > 1e-9 for p in entity.get_points(format="xyseb"))


def _polyline_has_bulge(entity):
    try:
        vertices = entity.vertices
        if callable(vertices):
            vertices = vertices()
        return any(abs(float(getattr(v.dxf, "bulge", 0.0))) > 1e-9 for v in vertices)
    except Exception:
        return False


def dxf_has_curved_geometry(document):
    curved = {"ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
    for entity in document.modelspace():
        kind = entity.dxftype()
        if kind in curved:
            return True
        if kind == "LWPOLYLINE" and _lwpolyline_has_bulge(entity):
            return True
        if kind == "POLYLINE" and _polyline_has_bulge(entity):
            return True
    return False


def _is_closed(entity):
    flag = entity.is_closed
    return bool(flag() if callable(flag) else flag)


def _lwpolyline_points(entity):
    if _lwpolyline_has_bulge(entity):
        return None
    return remove_consecutive_duplicates(
        [clean_point((p[0], p[1])) for p in entity.get_points(format="xy")]
    )


def _polyline_points(entity):
    if _polyline_has_bulge(entity):
        return None
    vertices = entity.vertices
    if callable(vertices):
        vertices = vertices()
    return remove_consecutive_duplicates(
        [clean_point((v.dxf.location.x, v.dxf.location.y)) for v in vertices]
    )


def _closed_loop_from_lines(segments, tolerance=1e-5):
    if not segments:
        return None
    unused = list(segments)
    first = unused.pop(0)
    loop = [first[0], first[1]]
    start = loop[0]

    while unused:
        end = loop[-1]
        if math.dist(end, start) <= tolerance and len(loop) >= 4:
            loop[-1] = start
            break
        found = None
        for index, (p1, p2) in enumerate(unused):
            if math.dist(p1, end) <= tolerance:
                found = (index, p2)
                break
            if math.dist(p2, end) <= tolerance:
                found = (index, p1)
                break
        if found is None:
            break
        index, nxt = found
        unused.pop(index)
        loop.append(nxt)

    if math.dist(loop[-1], start) > tolerance:
        return None
    loop[-1] = start
    return remove_consecutive_duplicates(loop)


def _simple_outer_points(document):
    modelspace = document.modelspace()
    candidates = []

    for entity in modelspace.query("LWPOLYLINE"):
        if entity.closed:
            pts = _lwpolyline_points(entity)
            if pts and len(pts) >= 3:
                candidates.append(pts)

    for entity in modelspace.query("POLYLINE"):
        if _is_closed(entity):
            pts = _polyline_points(entity)
            if pts and len(pts) >= 3:
                candidates.append(pts)

    if not candidates:
        segments = []
        for entity in modelspace.query("LINE"):
            s, e = entity.dxf.start, entity.dxf.end
            segments.append((clean_point((s.x, s.y)), clean_point((e.x, e.y))))
        pts = _closed_loop_from_lines(segments)
        if pts:
            candidates.append(pts)

    if not candidates:
        raise ValueError("No valid closed straight-line DXF boundary was found.")
    return max(candidates, key=lambda pts: abs(polygon_signed_area(pts)))


def _closed_like(entity):
    kind = entity.dxftype()
    if kind in {"CIRCLE", "ELLIPSE"}:
        return True
    if kind == "LWPOLYLINE":
        return bool(entity.closed)
    if kind == "POLYLINE":
        return _is_closed(entity)
    return False


def _resample(points, max_len):
    if len(points) < 2:
        return points
    out = [points[0]]
    for start, end in zip(points[:-1], points[1:]):
        steps = max(1, int(math.ceil(math.dist(start, end) / max_len)))
        for i in range(1, steps + 1):
            f = i / steps
            out.append(clean_point((start[0] + f * (end[0] - start[0]),
                                    start[1] + f * (end[1] - start[1]))))
    return out


def _entity_points(entity, segment_length, closing_tolerance):
    try:
        path_object = ezpath.make_path(entity)
        flatten = max(segment_length / 2.0, 0.05)
        pts = [clean_point((v.x, v.y)) for v in path_object.flattening(distance=flatten)]
        if len(pts) < 2:
            return []
        if _closed_like(entity) and pts[0] != pts[-1]:
            pts.append(pts[0])
        elif math.dist(pts[0], pts[-1]) <= closing_tolerance:
            pts[-1] = pts[0]
        return _resample(pts, segment_length)
    except Exception:
        return []


def _complex_outer_points(document, segment_length, closing_tolerance=None):
    if closing_tolerance is None:
        closing_tolerance = max(segment_length * 1.5, 0.5)

    supported = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
    lines, candidates = [], []

    for entity in document.modelspace():
        kind = entity.dxftype()
        if kind not in supported:
            continue
        if kind == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            lines.append(LineString([(s.x, s.y), (e.x, e.y)]))
            continue
        pts = _entity_points(entity, segment_length, closing_tolerance)
        if len(pts) < 2:
            continue
        lines.append(LineString(pts))
        if pts[0] == pts[-1] and len(pts) >= 4:
            poly = Polygon(pts[:-1])
            if poly.is_valid and poly.area > 0:
                candidates.append(poly)

    if lines:
        merged = unary_union(lines)
        snapped = snap(merged, merged, closing_tolerance)
        candidates.extend(
            p for p in polygonize(unary_union(snapped)) if p.is_valid and p.area > 0
        )

    if not candidates:
        raise ValueError(
            "No closed polygon could be created from the DXF geometry. "
            "Check that the outline is connected, or increase the segment length."
        )
    outer = max(candidates, key=lambda p: p.area)
    return [(float(x), float(y)) for x, y in list(outer.exterior.coords)[:-1]]


def import_dxf(path, segment_length):
    """Read a DXF file and return (outer_points, note)."""
    document = ezdxf.readfile(path)
    if dxf_has_curved_geometry(document):
        points = _complex_outer_points(document, segment_length)
        return points, "Curved entities detected; outline was discretized."
    try:
        return _simple_outer_points(document), "Straight-line outline imported as drawn."
    except Exception:
        points = _complex_outer_points(document, segment_length)
        return points, "Simple import failed; fallback conversion was used."
