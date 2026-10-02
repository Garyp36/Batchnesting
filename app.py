"""Sheet Metal Blank Nesting - Streamlit app."""

import os
import tempfile

import streamlit as st

from nesting.dxf_import import import_dxf
from nesting.engine import (
    DEFAULT_COARSE_STEP,
    DEFAULT_FINE_STEP,
    DEFAULT_FINE_WINDOW,
    DEFAULT_TOP_COARSE_ANGLES,
    default_settings,
    run_geometry_nesting,
)
from nesting.geometry import (
    SHAPES,
    build_standard_shape,
    format_points,
    make_geometry_entry,
    parse_points,
)
from nesting.plotting import figure_best_comparison, figure_geometry_preview, figure_top_four
from nesting.results import build_results_frame, geometry_summary_frame

import matplotlib.pyplot as plt

st.set_page_config(page_title="Sheet Metal Blank Nesting", page_icon="📐", layout="wide")

if "geometries" not in st.session_state:
    st.session_state.geometries = []
if "run" not in st.session_state:
    st.session_state.run = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def remove_geometry(index):
    st.session_state.geometries.pop(index)


def clear_geometries():
    st.session_state.geometries = []


def show_figure(fig):
    if fig is None:
        st.info("No valid layout to plot.")
        return
    st.pyplot(fig)
    plt.close(fig)


def shape_inputs(shape_name):
    values = {}
    columns = st.columns(2)
    for i, field in enumerate(SHAPES[shape_name]["fields"]):
        key = f"shape_{shape_name}_{field['key']}"
        with columns[i % 2]:
            if field["kind"] == "choice":
                values[field["key"]] = st.selectbox(field["label"], field["options"], key=key)
            elif field["kind"] == "int":
                values[field["key"]] = st.number_input(
                    field["label"], min_value=int(field["min"]), value=int(field["default"]),
                    step=1, key=key)
            else:
                values[field["key"]] = st.number_input(
                    field["label"], min_value=field["min"], value=float(field["default"]),
                    step=1.0, key=key)
    return values


def parameter_inputs(prefix):
    c1, c2, c3 = st.columns(3)
    with c1:
        num_rows = st.number_input("Number of rows", min_value=1, value=1, step=1, key=f"{prefix}_rows")
        origin_x = st.number_input("X offset from strip datum (mm)", min_value=0.0, value=6.0,
                                   key=f"{prefix}_ox")
    with c2:
        bottom = st.number_input("Bottom offset (mm)", min_value=0.0, value=6.0, key=f"{prefix}_bo")
        top = st.number_input("Top offset (mm)", min_value=0.0, value=6.0, key=f"{prefix}_to")
    with c3:
        x_gap = st.number_input("Minimum X gap between blanks (mm)", min_value=0.0, value=6.0,
                                key=f"{prefix}_xg")
        strip_length = st.number_input("Available strip length (mm)", min_value=1.0, value=1000.0,
                                       key=f"{prefix}_sl")
    row_gap = 0.0
    if num_rows > 1:
        row_gap = st.number_input("Row gap (mm)", min_value=0.0, value=6.0, key=f"{prefix}_rg")
    return {
        "num_rows": int(num_rows),
        "origin_x": origin_x,
        "bottom_offset": bottom,
        "top_offset": top,
        "x_gap": x_gap,
        "row_gap": row_gap,
        "strip_length": strip_length,
    }


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("Sheet Metal Blank Nesting")
st.caption("Add one or more blank geometries, set the strip parameters, and compare nesting layouts by yield.")

tab_geo, tab_run, tab_res = st.tabs(["1. Geometries", "2. Nesting & Run", "3. Results"])


# ---------------------------------------------------------------------------
# Tab 1: geometries
# ---------------------------------------------------------------------------

with tab_geo:
    st.subheader("Add a geometry")
    input_type = st.radio("Input type", ["Standard shape", "Coordinates", "DXF file"], horizontal=True)

    if input_type == "Standard shape":
        shape_name = st.selectbox("Shape", list(SHAPES.keys()))
        values = shape_inputs(shape_name)
        try:
            suggested, points = build_standard_shape(shape_name, values)
            error = None
        except ValueError as exc:
            suggested, points, error = shape_name, [], str(exc)

        if error:
            st.error(error)
        else:
            sig = hash((shape_name, tuple(sorted((k, str(v)) for k, v in values.items()))))
            coords_text = st.text_area(
                "Generated coordinates (editable, X,Y pairs separated by spaces)",
                value=format_points(points), key=f"coords_{sig}", height=100)
            name = st.text_input("Geometry name", value=suggested, key=f"name_{shape_name}")
            if st.button("Add geometry", type="primary", key="add_standard"):
                try:
                    entry = make_geometry_entry(name or suggested, "Standard/Coordinates",
                                                shape_name, parse_points(coords_text))
                    st.session_state.geometries.append(entry)
                    st.toast(f"Added {entry['name']}")
                except ValueError as exc:
                    st.error(str(exc))

    elif input_type == "Coordinates":
        coords_text = st.text_area("Outer boundary points (X,Y pairs separated by spaces)",
                                   placeholder="0,0 100,0 100,50 0,50", height=100, key="manual_coords")
        name = st.text_input("Geometry name", value="Custom Geometry", key="manual_name")
        if st.button("Add geometry", type="primary", key="add_manual"):
            try:
                entry = make_geometry_entry(name or "Custom Geometry", "Manual Coordinates",
                                            "Manual", parse_points(coords_text))
                st.session_state.geometries.append(entry)
                st.toast(f"Added {entry['name']}")
            except ValueError as exc:
                st.error(str(exc))

    else:
        upload = st.file_uploader("Upload a DXF file", type=["dxf"])
        segment_length = st.number_input("DXF segment length (mm)", min_value=0.05, value=1.0, step=0.5,
                                         help="Used to discretize arcs, circles and splines. "
                                              "Straight-line outlines are imported as drawn.")
        default_name = os.path.splitext(upload.name)[0] if upload else "DXF Geometry"
        name = st.text_input("Geometry name", value=default_name, key=f"dxf_name_{default_name}")
        if st.button("Add geometry", type="primary", key="add_dxf", disabled=upload is None):
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
                    tmp.write(upload.getvalue())
                    tmp_path = tmp.name
                points, note = import_dxf(tmp_path, segment_length)
                entry = make_geometry_entry(name or default_name, "DXF", upload.name,
                                            points, segment_length)
                st.session_state.geometries.append(entry)
                st.toast(f"Added {entry['name']}. {note}")
            except Exception as exc:
                st.error(f"DXF import failed: {exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

    st.divider()
    st.subheader("Geometries in this batch")
    geometries = st.session_state.geometries
    if not geometries:
        st.info("No geometries yet. Add at least one above.")
    else:
        st.dataframe(geometry_summary_frame(geometries), hide_index=True, width="stretch")
        for i, geometry in enumerate(geometries):
            with st.expander(f"{i + 1}. {geometry['name']}  ({geometry['area']:.1f} mm²)"):
                left, right = st.columns([1, 2])
                with left:
                    show_figure(figure_geometry_preview(geometry))
                with right:
                    min_x, min_y, max_x, max_y = geometry["polygon"].bounds
                    st.write(f"Bounding box: {max_x - min_x:.2f} × {max_y - min_y:.2f} mm")
                    st.write(f"Points: {len(geometry['points'])}")
                    st.button("Remove", key=f"rm_{i}", on_click=remove_geometry, args=(i,))
        st.button("Clear all", on_click=clear_geometries)


# ---------------------------------------------------------------------------
# Tab 2: parameters and run
# ---------------------------------------------------------------------------

with tab_run:
    geometries = st.session_state.geometries
    if not geometries:
        st.info("Add a geometry in the first tab before running a nesting.")

    st.subheader("Strip parameters")
    if len(geometries) > 1:
        parameter_mode = st.radio(
            "Parameter mode",
            ["Common parameters for all geometries", "Separate parameters for each geometry"],
            horizontal=True)
    else:
        parameter_mode = "Common parameters for all geometries"

    if parameter_mode.startswith("Common"):
        common = parameter_inputs("common")
        all_parameters = [dict(common) for _ in geometries]
    else:
        all_parameters = []
        for i, geometry in enumerate(geometries):
            with st.expander(f"Geometry {i + 1}: {geometry['name']}", expanded=(i == 0)):
                all_parameters.append(parameter_inputs(f"geo{i}"))

    st.divider()
    st.subheader("Search settings")
    settings = default_settings()
    mode_label = st.radio("Run mode", ["Auto (coarse-to-fine search)", "Manual"], horizontal=True)
    settings["run_mode"] = 2 if mode_label.startswith("Auto") else 1

    settings["pitch_step"] = st.select_slider(
        "Pitch search step (mm)", options=[0.25, 0.5, 1.0, 2.0], value=1.0,
        help="0.5 = detailed, 1.0 = balanced, 2.0 = fast.")

    if settings["run_mode"] == 2:
        settings["include_mirror"] = st.checkbox("Include mirror method", value=False)
        with st.expander("Advanced angle search"):
            a1, a2, a3, a4 = st.columns(4)
            settings["coarse_step"] = a1.number_input("Coarse step (deg)", min_value=1.0,
                                                      value=DEFAULT_COARSE_STEP)
            settings["fine_step"] = a2.number_input("Fine step (deg)", min_value=0.1,
                                                    value=DEFAULT_FINE_STEP)
            settings["fine_window"] = a3.number_input("Fine window (± deg)", min_value=0.0,
                                                      value=DEFAULT_FINE_WINDOW)
            settings["top_coarse_angles"] = int(a4.number_input(
                "Angles refined", min_value=1, value=DEFAULT_TOP_COARSE_ANGLES, step=1))
    else:
        methods = {
            "Bounding Box": 1,
            "Rotated Close-Stack": 2,
            "Alternate 0/180": 3,
            "Mirror Pair": 4,
        }
        method_label = st.selectbox("Manual method", list(methods.keys()))
        settings["manual_method"] = methods[method_label]
        if settings["manual_method"] in (2, 3, 4):
            settings["manual_angle_interval"] = st.number_input(
                "Angle interval (deg, 0 = only 0°)", min_value=0.0, value=0.0, step=1.0)
        if settings["manual_method"] == 4:
            mirror = st.radio("Mirror direction", ["Vertical", "Horizontal", "Both"], horizontal=True,
                              index=2)
            settings["manual_mirror_choice"] = ["Vertical", "Horizontal", "Both"].index(mirror) + 1

    st.divider()
    if st.button("Run nesting", type="primary", disabled=not geometries):
        runs = {"geometries": list(geometries), "parameters": all_parameters,
                "results": [], "counters": [], "elapsed": []}
        progress = st.progress(0.0, text="Starting...")
        for i, (geometry, parameters) in enumerate(zip(geometries, all_parameters)):
            progress.progress(i / len(geometries), text=f"Nesting {i + 1}/{len(geometries)}: {geometry['name']}")
            results, counters, elapsed = run_geometry_nesting(geometry, parameters, settings)
            runs["results"].append(results)
            runs["counters"].append(counters)
            runs["elapsed"].append(elapsed)
        progress.progress(1.0, text="Done")
        st.session_state.run = runs
        st.success("Nesting complete. Open the Results tab.")


# ---------------------------------------------------------------------------
# Tab 3: results
# ---------------------------------------------------------------------------

with tab_res:
    run = st.session_state.run
    if run is None:
        st.info("Run a nesting to see results here.")
    else:
        geos, params, all_results = run["geometries"], run["parameters"], run["results"]

        st.subheader("Best layout per geometry")
        cols = st.columns(min(len(geos), 4))
        for i, geometry in enumerate(geos):
            with cols[i % len(cols)]:
                if all_results[i]:
                    best = all_results[i][0]
                    st.metric(f"{i + 1}. {geometry['name']}", f"{best['yield_pct']:.2f}% yield",
                              f"{best['total_qty']} blanks | {best['method_name']} @ {best['angle']:.1f}°",
                              delta_color="off")
                else:
                    st.metric(f"{i + 1}. {geometry['name']}", "No valid layout")
                st.caption(f"{run['counters'][i]['valid']}/{run['counters'][i]['total']} valid layouts, "
                           f"{run['elapsed'][i]:.1f} s")

        frame = build_results_frame(geos, all_results)
        if frame.empty:
            st.warning("No valid layouts were found. Check strip length, offsets and gaps.")
        else:
            st.subheader("Top four layouts per geometry")
            columns = ["Geometry No.", "Geometry Name", "Rank", "Method", "Angle (deg)", "Quantity",
                       "Pitch (mm)", "Strip Width (mm)", "Used Length (mm)", "Yield (%)", "Scrap (%)"]
            st.dataframe(frame[columns], hide_index=True, width="stretch")
            st.download_button("Download results (CSV)", frame.to_csv(index=False).encode("utf-8"),
                               file_name="batch_nesting_results.csv", mime="text/csv")

            st.subheader("Plots")
            valid_numbers = [i + 1 for i, r in enumerate(all_results) if r]
            labels = {n: f"{n}. {geos[n - 1]['name']}" for n in valid_numbers}
            plot_mode = st.radio("Plot type", ["Top four layouts for one geometry",
                                               "Best layout comparison (up to four geometries)"],
                                 horizontal=True)
            if plot_mode.startswith("Top four"):
                number = st.selectbox("Geometry", valid_numbers, format_func=lambda n: labels[n])
                show_figure(figure_top_four(number, geos[number - 1], all_results[number - 1],
                                            params[number - 1]))
            else:
                chosen = st.multiselect("Geometries", valid_numbers, default=valid_numbers[:4],
                                        format_func=lambda n: labels[n], max_selections=4)
                if chosen:
                    show_figure(figure_best_comparison(chosen, geos, all_results, params))
