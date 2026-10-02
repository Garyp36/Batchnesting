# Sheet Metal Blank Nesting

Streamlit app that nests sheet metal blanks on a strip and ranks layouts by material yield.

## What it does

- Accepts standard shapes (rectangle, triangles, trapezoid, L, T, circle, ellipse, regular polygon), typed coordinates, or DXF files
- Batch mode: add as many geometries as you want, with common or per-geometry strip parameters
- Methods: bounding box, rotated close-stack, alternate 0/180 interlocking, mirror pair
- Auto mode searches angles coarse-to-fine; manual mode runs one method at a chosen angle interval
- Shows the top four layouts per geometry, plots them, and exports a CSV

## Project layout

```
app.py                  Streamlit interface
nesting/
  geometry.py           Polygon helpers and standard shape builders
  dxf_import.py         DXF boundary import
  engine.py             Nesting algorithms and angle search
  results.py            Result tables
  plotting.py           Matplotlib figures
requirements.txt
.streamlit/config.toml
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repository (files at the repo root, so `app.py` and `requirements.txt` sit next to each other).
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Choose **Create app**, pick the repository and branch, and set the main file path to `app.py`.
4. Under **Advanced settings**, choose Python 3.11 or 3.12.
5. Deploy.

## Notes

- Units are millimetres.
- Auto mode with mirror enabled and a 0.5 mm pitch step can take a while on shapes with many points. Start with a 1.0 mm step.
- The overlap check uses a spatial index, so it is faster than a plain pairwise check but returns the same answer.
