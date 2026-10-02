"""Matplotlib figures for the Streamlit app (figures are returned, never shown)."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def plot_nesting_on_axis(axis, result, strip_length, title):
    strip_width = result["strip_width"]
    axis.plot([0, strip_length, strip_length, 0, 0], [0, 0, strip_width, strip_width, 0], "k-", linewidth=2)
    types = result.get("placed_types")
    for index, polygon in enumerate(result["placed_polygons"]):
        color = "tab:blue" if not types or types[index] == "A" else "tab:orange"
        xs, ys = polygon.exterior.xy
        axis.plot(xs, ys, color=color, linewidth=1.2)
    axis.set_aspect("equal")
    axis.grid(True, alpha=0.35)
    axis.set_xlim(-0.02 * strip_length, 1.02 * strip_length)
    axis.set_ylim(-0.05 * strip_width, 1.08 * strip_width)
    axis.set_title(title, fontsize=9)
    axis.set_xlabel("Strip Length X (mm)")
    axis.set_ylabel("Strip Width Y (mm)")


def _title(number, geometry, result, rank=None):
    head = f"Geometry {number}: {geometry['name']}"
    if rank is not None:
        head += f" | Rank {rank}"
    return (f"{head}\n{result['method_name']} | Angle {result['angle']:.2f} deg | "
            f"Yield {result['yield_pct']:.2f}%")


def figure_top_four(number, geometry, results, parameters):
    top = results[:4]
    if not top:
        return None
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    axes = axes.flatten()
    for i, result in enumerate(top):
        plot_nesting_on_axis(axes[i], result, parameters["strip_length"], _title(number, geometry, result, i + 1))
    for i in range(len(top), 4):
        axes[i].axis("off")
    fig.suptitle(f"Top four layouts: Geometry {number} - {geometry['name']}", fontweight="bold")
    fig.tight_layout()
    return fig


def figure_best_comparison(numbers, geometries, all_results, all_parameters):
    """numbers are 1-based geometry numbers, at most four."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    axes = axes.flatten()
    used = 0
    for number in numbers[:4]:
        index = number - 1
        if not all_results[index]:
            continue
        result = all_results[index][0]
        plot_nesting_on_axis(axes[used], result, all_parameters[index]["strip_length"],
                             _title(number, geometries[index], result))
        used += 1
    if used == 0:
        plt.close(fig)
        return None
    for i in range(used, 4):
        axes[i].axis("off")
    fig.suptitle("Best layout comparison", fontweight="bold")
    fig.tight_layout()
    return fig


def figure_geometry_preview(geometry):
    fig, axis = plt.subplots(figsize=(4, 3))
    xs, ys = geometry["polygon"].exterior.xy
    axis.fill(xs, ys, alpha=0.25, color="tab:blue")
    axis.plot(xs, ys, color="tab:blue", linewidth=1.5)
    axis.set_aspect("equal")
    axis.grid(True, alpha=0.35)
    axis.set_xlabel("X (mm)")
    axis.set_ylabel("Y (mm)")
    fig.tight_layout()
    return fig
