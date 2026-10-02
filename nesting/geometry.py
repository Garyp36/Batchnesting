"""Geometry helpers and standard-shape builders (no UI code)."""

import math

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon
from shapely.strtree import STRtree

OVERLAP_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------

def parse_points(text):
    """Parse 'x,y x,y ...' (spaces, semicolons or new lines between pairs)."""
    points = []
    for token in text.replace(";", " ").split():
        try:
            x_value, y_value = token.split(",")
            points.append((float(x_value), float(y_value)))
        except ValueError:
            raise ValueError(
                f"Cannot read '{token}'. Use X,Y pairs separated by spaces, e.g. 0,0 10,0 0,20."
            ) from None
    return points


def format_points(points):
    return " ".join(f"{x:.6g},{y:.6g}" for x, y in points)


def polygon_signed_area(points):
    total = 0.0
    count = len(points)
    for i in range(count):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % count]
        total += x1 * y2 - y1 * x2
    return total / 2.0


def clean_point(point, decimals=6):
    return round(float(point[0]), decimals), round(float(point[1]), decimals)


def remove_consecutive_duplicates(points, tolerance=1e-9):
    cleaned = []
    for point in points:
        if not cleaned or math.dist(point, cleaned[-1]) > tolerance:
            cleaned.append(point)
    if len(cleaned) > 1 and math.dist(cleaned[0], cleaned[-1]) <= tolerance:
        cleaned.pop()
    return cleaned


def create_valid_polygon(points, geometry_name="Geometry"):
    points = remove_consecutive_duplicates(points)
    if len(points) < 3:
        raise ValueError(f"{geometry_name}: at least three unique points are required.")

    polygon = Polygon(points)
    if polygon.is_empty or polygon.area <= 0:
        raise ValueError(f"{geometry_name}: polygon area must be greater than zero.")

    if not polygon.is_valid:
        repaired = polygon.buffer(0)
        if repaired.is_empty or repaired.geom_type != "Polygon" or not repaired.is_valid:
            raise ValueError(f"{geometry_name}: polygon is invalid or self-intersecting.")
        polygon = repaired
        points = list(polygon.exterior.coords)[:-1]

    return polygon, [(float(x), float(y)) for x, y in points]


def make_geometry_entry(name, input_type, source, points, segment_length=None):
    """Validate points and return the geometry record used throughout the app."""
    polygon, points = create_valid_polygon(points, name)
    return {
        "name": name,
        "input_type": input_type,
        "source": source,
        "segment_length": segment_length,
        "points": points,
        "polygon": polygon,
        "area": polygon.area,
    }


def normalize_polygon(polygon):
    min_x, min_y, _, _ = polygon.bounds
    return translate(polygon, xoff=-min_x, yoff=-min_y)


def safe_rotate(polygon, angle, origin="centroid"):
    if abs(angle % 360.0) < 1e-9:
        return polygon
    return rotate(polygon, angle, origin=origin)


def overlap_area(polygon_1, polygon_2):
    return polygon_1.intersection(polygon_2).area


def has_overlap(polygons, tolerance=OVERLAP_TOLERANCE):
    """Same result as a pairwise check, but a spatial index skips distant pairs."""
    if len(polygons) < 2:
        return False
    tree = STRtree(polygons)
    for i, polygon in enumerate(polygons):
        for j in tree.query(polygon):
            if j > i and overlap_area(polygon, polygons[int(j)]) > tolerance:
                return True
    return False


# ---------------------------------------------------------------------------
# Curved-shape point generators
# ---------------------------------------------------------------------------

def circle_points(diameter, segment_length):
    radius = diameter / 2.0
    count = max(12, int(math.ceil(2.0 * math.pi * radius / segment_length)))
    return [
        (
            radius + radius * math.cos(2.0 * math.pi * i / count),
            radius + radius * math.sin(2.0 * math.pi * i / count),
        )
        for i in range(count)
    ]


def ellipse_points(major_diameter, minor_diameter, segment_length):
    a = major_diameter / 2.0
    b = minor_diameter / 2.0
    perimeter = math.pi * (3.0 * (a + b) - math.sqrt((3.0 * a + b) * (a + 3.0 * b)))
    count = max(16, int(math.ceil(perimeter / segment_length)))
    return [
        (
            a + a * math.cos(2.0 * math.pi * i / count),
            b + b * math.sin(2.0 * math.pi * i / count),
        )
        for i in range(count)
    ]


def regular_polygon_points(sides, size_value, size_mode, start_angle_degrees):
    """size_mode: 1 circumscribed radius, 2 inscribed radius, 3 side length."""
    if sides < 3:
        raise ValueError("Regular polygon requires at least three sides.")
    if size_mode == 1:
        radius = size_value
    elif size_mode == 2:
        radius = size_value / math.cos(math.pi / sides)
    elif size_mode == 3:
        radius = size_value / (2.0 * math.sin(math.pi / sides))
    else:
        raise ValueError("Invalid regular polygon size mode.")

    start = math.radians(start_angle_degrees)
    return [
        (
            radius + radius * math.cos(start + 2.0 * math.pi * i / sides),
            radius + radius * math.sin(start + 2.0 * math.pi * i / sides),
        )
        for i in range(sides)
    ]


# ---------------------------------------------------------------------------
# Standard shape registry (drives the Streamlit form generically)
# ---------------------------------------------------------------------------

def _f(key, label, default, kind="float", minimum=0.001, options=None):
    return {"key": key, "label": label, "default": default, "kind": kind,
            "min": minimum, "options": options}


def _rectangle(p):
    return [(0, 0), (p["length"], 0), (p["length"], p["width"]), (0, p["width"])]


def _right_triangle(p):
    return [(0, 0), (p["base"], 0), (0, p["height"])]


def _general_triangle(p):
    return [(p["x1"], p["y1"]), (p["x2"], p["y2"]), (p["x3"], p["y3"])]


def _trapezoid(p):
    offset = (p["bottom"] - p["top"]) / 2.0
    return [(0, 0), (p["bottom"], 0), (offset + p["top"], p["height"]), (offset, p["height"])]


def _l_shape(p):
    if p["h_thk"] >= p["height"] or p["v_thk"] >= p["length"]:
        raise ValueError("Leg thicknesses must be smaller than the overall dimensions.")
    return [
        (0, 0), (p["length"], 0), (p["length"], p["h_thk"]),
        (p["v_thk"], p["h_thk"]), (p["v_thk"], p["height"]), (0, p["height"]),
    ]


def _t_shape(p):
    if p["flange"] >= p["height"] or p["stem"] >= p["width"]:
        raise ValueError("Flange thickness and stem width must be smaller than overall dimensions.")
    left = (p["width"] - p["stem"]) / 2.0
    right = left + p["stem"]
    neck = p["height"] - p["flange"]
    return [
        (0, neck), (left, neck), (left, 0), (right, 0),
        (right, neck), (p["width"], neck), (p["width"], p["height"]), (0, p["height"]),
    ]


def _circle(p):
    return circle_points(p["diameter"], p["segment"])


def _ellipse(p):
    return ellipse_points(p["major"], p["minor"], p["segment"])


SIZE_MODES = ["Circumscribed radius", "Inscribed radius", "Side length"]


def _regular_polygon(p):
    return regular_polygon_points(
        int(p["sides"]), p["size"], SIZE_MODES.index(p["size_mode"]) + 1, p["start_angle"]
    )


SHAPES = {
    "Rectangle": {
        "fields": [_f("length", "Length (mm)", 100.0), _f("width", "Width (mm)", 50.0)],
        "build": _rectangle,
    },
    "Right Triangle": {
        "fields": [_f("base", "Base (mm)", 10.0), _f("height", "Height (mm)", 20.0)],
        "build": _right_triangle,
    },
    "General Triangle": {
        "fields": [
            _f("x1", "Point 1 X", 0.0, minimum=None), _f("y1", "Point 1 Y", 0.0, minimum=None),
            _f("x2", "Point 2 X", 40.0, minimum=None), _f("y2", "Point 2 Y", 0.0, minimum=None),
            _f("x3", "Point 3 X", 10.0, minimum=None), _f("y3", "Point 3 Y", 30.0, minimum=None),
        ],
        "build": _general_triangle,
    },
    "Trapezoid": {
        "fields": [
            _f("bottom", "Bottom width (mm)", 60.0),
            _f("top", "Top width (mm)", 30.0),
            _f("height", "Height (mm)", 25.0),
        ],
        "build": _trapezoid,
    },
    "L-Shape": {
        "fields": [
            _f("length", "Overall length (mm)", 80.0),
            _f("height", "Overall height (mm)", 60.0),
            _f("h_thk", "Horizontal-leg thickness (mm)", 20.0),
            _f("v_thk", "Vertical-leg thickness (mm)", 20.0),
        ],
        "build": _l_shape,
    },
    "T-Shape": {
        "fields": [
            _f("width", "Overall width (mm)", 80.0),
            _f("height", "Overall height (mm)", 60.0),
            _f("flange", "Top-flange thickness (mm)", 15.0),
            _f("stem", "Stem width (mm)", 25.0),
        ],
        "build": _t_shape,
    },
    "Circle": {
        "fields": [_f("diameter", "Diameter (mm)", 50.0), _f("segment", "Curve segment length (mm)", 2.0)],
        "build": _circle,
    },
    "Ellipse": {
        "fields": [
            _f("major", "Major diameter (mm)", 80.0),
            _f("minor", "Minor diameter (mm)", 40.0),
            _f("segment", "Curve segment length (mm)", 2.0),
        ],
        "build": _ellipse,
    },
    "Regular Polygon": {
        "fields": [
            _f("sides", "Number of sides", 6, kind="int", minimum=3),
            _f("size_mode", "Size definition", SIZE_MODES[0], kind="choice", options=SIZE_MODES),
            _f("size", "Size value (mm)", 30.0),
            _f("start_angle", "Starting angle (deg)", 0.0, minimum=None),
        ],
        "build": _regular_polygon,
    },
}


def build_standard_shape(shape_name, values):
    """Return (suggested_name, points) for a standard shape."""
    spec = SHAPES[shape_name]
    points = spec["build"](values)
    name = shape_name
    if shape_name == "Regular Polygon":
        name = f"Regular Polygon ({int(values['sides'])} sides)"
    return name, [(float(x), float(y)) for x, y in points]
