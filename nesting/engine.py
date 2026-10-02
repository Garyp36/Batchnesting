"""Nesting algorithms: bounding box, rotated close-stack, alternate 0/180, mirror pair."""

import math
import time

import numpy as np
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString

from .geometry import (
    OVERLAP_TOLERANCE,
    has_overlap,
    normalize_polygon,
    overlap_area,
    safe_rotate,
)

DEFAULT_COARSE_STEP = 10.0
DEFAULT_FINE_STEP = 2.0
DEFAULT_FINE_WINDOW = 10.0
DEFAULT_TOP_COARSE_ANGLES = 3


# ---------------------------------------------------------------------------
# Pitch search
# ---------------------------------------------------------------------------

def find_minimum_close_pitch(polygon, x_gap, step, tolerance=OVERLAP_TOLERANCE):
    min_x, _, max_x, _ = polygon.bounds
    pitch = last_safe = max_x - min_x
    while pitch >= 0:
        if overlap_area(polygon, translate(polygon, xoff=pitch)) > tolerance:
            break
        last_safe = pitch
        pitch -= step
    return max(0.0, last_safe) + x_gap


def find_minimum_pitch_between(left, right, x_gap, step, tolerance=OVERLAP_TOLERANCE):
    min_x, _, max_x, _ = left.bounds
    pitch = last_safe = max_x - min_x
    while pitch >= 0:
        if overlap_area(left, translate(right, xoff=pitch)) > tolerance:
            break
        last_safe = pitch
        pitch -= step
    return max(0.0, last_safe) + x_gap


# ---------------------------------------------------------------------------
# Layout evaluation
# ---------------------------------------------------------------------------

def _strip_width(parameters, part_height):
    return (
        parameters["bottom_offset"]
        + parameters["num_rows"] * part_height
        + (parameters["num_rows"] - 1) * parameters["row_gap"]
        + parameters["top_offset"]
    )


def evaluate_single_nesting(polygon, blank_area, parameters, method, pitch_step):
    polygon = normalize_polygon(polygon)
    min_x, min_y, max_x, max_y = polygon.bounds
    part_length = max_x - min_x
    part_height = max_y - min_y

    if method == "BOUNDING":
        pitch_x = part_length + parameters["x_gap"]
    else:
        pitch_x = find_minimum_close_pitch(polygon, parameters["x_gap"], pitch_step)

    strip_width = _strip_width(parameters, part_height)

    qty_per_row = 0
    current_x = parameters["origin_x"]
    while current_x + part_length <= parameters["strip_length"] + 1e-9:
        qty_per_row += 1
        current_x += pitch_x
    if qty_per_row == 0:
        return None

    placed = []
    for row in range(parameters["num_rows"]):
        row_y = parameters["bottom_offset"] + row * (part_height + parameters["row_gap"])
        for col in range(qty_per_row):
            placed.append(translate(polygon, xoff=parameters["origin_x"] + col * pitch_x, yoff=row_y))

    if has_overlap(placed):
        return None

    total_qty = qty_per_row * parameters["num_rows"]
    used_length = parameters["origin_x"] + (qty_per_row - 1) * pitch_x + part_length
    input_area = used_length * strip_width
    yield_pct = 100.0 * total_qty * blank_area / input_area if input_area > 0 else 0.0

    return {
        "part_length": part_length,
        "part_height": part_height,
        "pitch_x": pitch_x,
        "strip_width": strip_width,
        "qty_per_row": qty_per_row,
        "total_qty": total_qty,
        "used_strip_length": used_length,
        "input_strip_area": input_area,
        "utilized_blank_area": total_qty * blank_area,
        "yield_pct": yield_pct,
        "placed_polygons": placed,
    }


def evaluate_pair_nesting(polygon_a, polygon_b, angle, blank_area, parameters, pitch_step):
    polygon_a = normalize_polygon(polygon_a)
    polygon_b = normalize_polygon(polygon_b)

    ax0, ay0, ax1, ay1 = polygon_a.bounds
    bx0, by0, bx1, by1 = polygon_b.bounds
    length_a, length_b = ax1 - ax0, bx1 - bx0
    part_height = max(ay1 - ay0, by1 - by0)

    pitch_ab = find_minimum_pitch_between(polygon_a, polygon_b, parameters["x_gap"], pitch_step)
    pitch_ba = find_minimum_pitch_between(polygon_b, polygon_a, parameters["x_gap"], pitch_step)
    strip_width = _strip_width(parameters, part_height)

    placed, placed_types = [], []
    qty_per_row = 0

    for row in range(parameters["num_rows"]):
        row_y = parameters["bottom_offset"] + row * (part_height + parameters["row_gap"])
        x_position = parameters["origin_x"]
        col = 0
        while True:
            if col % 2 == 0:
                poly, length, kind = polygon_a, length_a, "A"
            else:
                poly, length, kind = polygon_b, length_b, "B"
            if x_position + length > parameters["strip_length"] + 1e-9:
                break
            placed.append(translate(poly, xoff=x_position, yoff=row_y))
            placed_types.append(kind)
            if row == 0:
                qty_per_row += 1
            x_position += pitch_ab if col % 2 == 0 else pitch_ba
            col += 1

    total_qty = qty_per_row * parameters["num_rows"]
    if total_qty == 0 or has_overlap(placed):
        return None

    used_length = max(p.bounds[2] for p in placed)
    input_area = used_length * strip_width
    yield_pct = 100.0 * total_qty * blank_area / input_area if input_area > 0 else 0.0

    return {
        "part_length": max(length_a, length_b),
        "part_height": part_height,
        "pitch_x": (pitch_ab + pitch_ba) / 2.0,
        "pitch_ab": pitch_ab,
        "pitch_ba": pitch_ba,
        "strip_width": strip_width,
        "qty_per_row": qty_per_row,
        "total_qty": total_qty,
        "used_strip_length": used_length,
        "input_strip_area": input_area,
        "utilized_blank_area": total_qty * blank_area,
        "yield_pct": yield_pct,
        "placed_polygons": placed,
        "placed_types": placed_types,
        "angle": angle,
    }


def _longest_edge(polygon):
    coords = list(polygon.exterior.coords)
    best_line, best_len, best_angle = None, 0.0, 0.0
    for start, end in zip(coords[:-1], coords[1:]):
        line = LineString([start, end])
        if line.length > best_len:
            best_line, best_len = line, line.length
            best_angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 180.0
    return best_line, best_len, best_angle


def longest_edge_alignment(poly_1, poly_2, parallel_tolerance=5.0):
    e1, l1, a1 = _longest_edge(poly_1)
    e2, l2, a2 = _longest_edge(poly_2)
    diff = abs(a1 - a2)
    if diff > 90.0:
        diff = 180.0 - diff
    return {
        "long_edge_gap": e1.distance(e2),
        "long_edge_a": l1,
        "long_edge_b": l2,
        "long_edge_angle_a": a1,
        "long_edge_angle_b": a2,
        "long_edge_angle_diff": diff,
        "long_edge_parallel": diff <= parallel_tolerance,
    }


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------

def run_bounding_method(geometry, parameters, pitch_step, prefix=""):
    polygon = geometry["polygon"]
    min_x, min_y, max_x, max_y = polygon.bounds
    if max_y - min_y > max_x - min_x:
        polygon = rotate(polygon, -90, origin="centroid")

    result = evaluate_single_nesting(polygon, geometry["area"], parameters, "BOUNDING", pitch_step)
    if result:
        result.update(
            method_no=1, method_name="Bounding Box", angle=0.0, mirror_direction=None,
            display_name=f"{prefix}Method 1 - Bounding Box".strip(),
        )
    return result


def run_rotated_method(geometry, angle, parameters, pitch_step, prefix=""):
    polygon = safe_rotate(geometry["polygon"], angle)
    result = evaluate_single_nesting(polygon, geometry["area"], parameters, "ROTATED", pitch_step)
    if result:
        result.update(
            method_no=2, method_name="Rotated Close-Stack", angle=float(angle), mirror_direction=None,
            display_name=f"{prefix}Method 2 - Rotated {angle:.2f} deg".strip(),
        )
    return result


def run_alternate_method(geometry, angle, parameters, pitch_step, prefix=""):
    polygon_a = safe_rotate(geometry["polygon"], angle)
    polygon_b = safe_rotate(geometry["polygon"], angle + 180.0)
    result = evaluate_pair_nesting(polygon_a, polygon_b, angle, geometry["area"], parameters, pitch_step)
    if result:
        result.update(
            method_no=3, method_name="Alternate 0/180 Interlocking", angle=float(angle),
            mirror_direction=None,
            display_name=f"{prefix}Method 3 - Alternate 0/180, Base {angle:.2f} deg".strip(),
        )
    return result


def run_mirror_method(geometry, angle, mirror_direction, parameters, pitch_step, prefix=""):
    polygon_a = safe_rotate(geometry["polygon"], angle)
    if mirror_direction == 1:
        polygon_b = scale(polygon_a, xfact=-1, yfact=1, origin="centroid")
        mirror_text = "Vertical Mirror"
    else:
        polygon_b = scale(polygon_a, xfact=1, yfact=-1, origin="centroid")
        mirror_text = "Horizontal Mirror"

    result = evaluate_pair_nesting(polygon_a, polygon_b, angle, geometry["area"], parameters, pitch_step)
    if result and result["qty_per_row"] >= 2:
        result.update(longest_edge_alignment(result["placed_polygons"][0], result["placed_polygons"][1]))
        result.update(
            method_no=4, method_name="Mirror Pair Nesting", angle=float(angle),
            mirror_direction=mirror_direction, mirror_text=mirror_text,
            display_name=f"{prefix}Method 4 - {mirror_text}, Angle {angle:.2f} deg".strip(),
        )
        return result
    return None


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def result_sort_key(result):
    return (result["yield_pct"], result["total_qty"], -result["used_strip_length"], -result["pitch_x"])


def make_fine_angle_list(center, maximum_angle, fine_step, fine_window):
    angles = []
    value = center - fine_window
    while value <= center + fine_window + 1e-9:
        if maximum_angle == 360:
            angles.append(round(value % 360.0, 6))
        elif 0 <= value < maximum_angle:
            angles.append(round(value, 6))
        value += fine_step
    return sorted(set(angles))


def best_center_angles(results, top_n):
    return [r["angle"] for r in sorted(results, key=result_sort_key, reverse=True)[:top_n]]


def coarse_to_fine_search(run_function, maximum_angle, coarse_step, fine_step, fine_window, top_n):
    results = []
    counters = {"total": 0, "valid": 0, "invalid": 0}
    evaluated = set()
    coarse_results = []

    for angle in np.arange(0, maximum_angle, coarse_step):
        angle = float(angle)
        evaluated.add(round(angle, 6))
        counters["total"] += 1
        result = run_function(angle, "Auto Coarse ")
        if result:
            coarse_results.append(result)
            results.append(result)
            counters["valid"] += 1
        else:
            counters["invalid"] += 1

    fine_angles = []
    for center in best_center_angles(coarse_results, top_n):
        fine_angles.extend(make_fine_angle_list(center, maximum_angle, fine_step, fine_window))

    for angle in sorted(set(fine_angles)):
        if round(angle, 6) in evaluated:
            continue
        evaluated.add(round(angle, 6))
        counters["total"] += 1
        result = run_function(angle, "Auto Fine ")
        if result:
            results.append(result)
            counters["valid"] += 1
        else:
            counters["invalid"] += 1

    return results, counters


def _combine(target, addition):
    for key in target:
        target[key] += addition[key]


def default_settings():
    return {
        "run_mode": 2,  # 1 manual, 2 auto
        "pitch_step": 1.0,
        "include_mirror": True,
        "coarse_step": DEFAULT_COARSE_STEP,
        "fine_step": DEFAULT_FINE_STEP,
        "fine_window": DEFAULT_FINE_WINDOW,
        "top_coarse_angles": DEFAULT_TOP_COARSE_ANGLES,
        "manual_method": 1,
        "manual_angle_interval": 0.0,
        "manual_mirror_choice": 3,
    }


def run_geometry_nesting(geometry, parameters, settings):
    """Return (sorted_results, counters, elapsed_seconds)."""
    results = []
    counters = {"total": 0, "valid": 0, "invalid": 0}
    start = time.perf_counter()
    pitch_step = settings["pitch_step"]

    def add(result):
        counters["total"] += 1
        if result:
            results.append(result)
            counters["valid"] += 1
        else:
            counters["invalid"] += 1

    if settings["run_mode"] == 1:
        method = settings["manual_method"]
        interval = settings.get("manual_angle_interval", 0.0)
        if method == 1:
            add(run_bounding_method(geometry, parameters, pitch_step, "Manual "))
        elif method == 2:
            for angle in ([0.0] if interval == 0 else np.arange(0, 360, interval)):
                add(run_rotated_method(geometry, float(angle), parameters, pitch_step, "Manual "))
        elif method == 3:
            for angle in ([0.0] if interval == 0 else np.arange(0, 180, interval)):
                add(run_alternate_method(geometry, float(angle), parameters, pitch_step, "Manual "))
        else:
            choice = settings["manual_mirror_choice"]
            directions = [1] if choice == 1 else [2] if choice == 2 else [1, 2]
            angles = [0.0] if interval == 0 else np.arange(0, 360, interval)
            for direction in directions:
                for angle in angles:
                    add(run_mirror_method(geometry, float(angle), direction, parameters, pitch_step, "Manual "))
    else:
        search = (settings["coarse_step"], settings["fine_step"],
                  settings["fine_window"], settings["top_coarse_angles"])

        add(run_bounding_method(geometry, parameters, pitch_step, "Auto "))

        found, counts = coarse_to_fine_search(
            lambda a, p: run_rotated_method(geometry, a, parameters, pitch_step, p), 360, *search)
        results.extend(found)
        _combine(counters, counts)

        found, counts = coarse_to_fine_search(
            lambda a, p: run_alternate_method(geometry, a, parameters, pitch_step, p), 180, *search)
        results.extend(found)
        _combine(counters, counts)

        if settings["include_mirror"]:
            for direction in (1, 2):
                found, counts = coarse_to_fine_search(
                    lambda a, p, d=direction: run_mirror_method(geometry, a, d, parameters, pitch_step, p),
                    360, *search)
                results.extend(found)
                _combine(counters, counts)

    elapsed = time.perf_counter() - start
    results.sort(key=result_sort_key, reverse=True)
    for result in results:
        result["execution_time_sec"] = elapsed
    return results, counters, elapsed
