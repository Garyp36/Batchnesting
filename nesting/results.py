"""Result tables."""

import pandas as pd


def result_rows_for_geometry(number, geometry, results, top_n=4):
    rows = []
    for rank, result in enumerate(results[:top_n], start=1):
        rows.append({
            "Geometry No.": number,
            "Geometry Name": geometry["name"],
            "Input Type": geometry["input_type"],
            "Rank": rank,
            "Method": result["method_name"],
            "Method Details": result["display_name"],
            "Angle (deg)": round(result["angle"], 3),
            "Quantity": result["total_qty"],
            "Pitch (mm)": round(result["pitch_x"], 3),
            "Strip Width (mm)": round(result["strip_width"], 3),
            "Used Length (mm)": round(result["used_strip_length"], 3),
            "Yield (%)": round(result["yield_pct"], 3),
            "Scrap (%)": round(100.0 - result["yield_pct"], 3),
            "Blank Area (mm2)": round(geometry["area"], 3),
            "Execution Time (s)": round(result.get("execution_time_sec", 0.0), 3),
        })
    return rows


def build_results_frame(geometries, all_results, top_n=4):
    rows = []
    for number, (geometry, results) in enumerate(zip(geometries, all_results), start=1):
        rows.extend(result_rows_for_geometry(number, geometry, results, top_n))
    return pd.DataFrame(rows)


def geometry_summary_frame(geometries):
    return pd.DataFrame([
        {
            "No.": i,
            "Geometry": g["name"],
            "Input Type": g["input_type"],
            "Points": len(g["points"]),
            "Area (mm2)": round(g["area"], 3),
        }
        for i, g in enumerate(geometries, start=1)
    ])
