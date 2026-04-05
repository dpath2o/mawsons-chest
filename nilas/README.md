# mawsons-chest

A lightweight toolbox for **direct CICE ice-history analysis and figure generation**.

`mawsons-chest` is designed for workflows built around native `iceh.*.nc` files, with no requirement to first reorganise the data into Zarr stores. The current plotting and diagnostics flow is centered on the `cice_basics` class in `src/cice_netcdf_tools.py`.

## What it does

The toolbox is aimed at fast, day-by-day analysis and visualisation of sea-ice diagnostics from CICE, with optional comparison against daily NSIDC concentration products.

Core capabilities include:

- loading a single CICE history file for a requested day
- correcting the CICE in-file timestamp to the nominal model day
- preparing native-grid CICE variables for PyGMT plotting using embedded 2D coordinates
- computing hemispheric sea-ice extent from `aice` and `tarea`
- computing hemispheric sea-ice area, sea-ice volume, and aggregate sea-ice thickness from `aice`, `hi`, and `tarea`
- loading daily NSIDC sea-ice concentration files
- computing NSIDC daily SIA/SIE using official NSIDC0771 cell-area ancillaries
- extracting the NSIDC 15% concentration contour for map overlays
- producing side-by-side southern / northern hemisphere maps for:
  - sea-ice concentration (`aice`)
  - sea-ice thickness (`hi`)
- generating time-evolving frames and simple GIF / MP4 animations

## Repository layout

```text
mawsons-chest/
├── README.md
└── src/
    └── cice_netcdf_tools.py
```

A typical workflow is:

1. open a single CICE daily history file
2. compute a corrected date string from the in-file timestamp
3. prepare a variable such as `aice` or `hi` for plotting
4. compute hemispheric diagnostics for annotation
5. optionally load the matching NSIDC daily file and overlay the 15% contour
6. save a figure or render a sequence into an animation

## Installation

Clone the repository and install the scientific Python stack required by the module.

```bash
git clone https://github.com/dpath2o/mawsons-chest.git
cd mawsons-chest
```

A minimal environment will usually need:

```bash
pip install numpy pandas xarray matplotlib pyproj imageio notebook
```

For plotting, install:

```bash
pip install pygmt
```

On NCI / Gadi, you will also want the system GMT installation and the same Python environment that already supports your CICE / PyGMT workflows.

## Quick start

Assuming the repository root is on your Python path and the default directories match your current Gadi layout:

```python
from src.mawsons_tools import toolbelt

tb = toolbelt()

# Plot daily sea-ice concentration with southern NSIDC contour
tb.plot_aice_day("1993-04-24", add_nsidc_south=True, show=True)

# Plot daily sea-ice thickness
tb.plot_hi_day("1993-04-24", show=True)
```

## Example with explicit paths

If you want to override the defaults at initialisation:

```python
from pathlib import Path
from src.cice_netcdf_tools import cice_basics

tb = cice_basics(cice_history_dir      = Path("/g/data/gv90/da1339/cice-dirs/runs/free-slip-waves/history"),
                 nsidc_daily_south_dir = Path("/g/data/gv90/da1339/SeaIce/NSIDC/G02202_V4/south/daily"),
                 nsidc_daily_north_dir = Path("/g/data/gv90/da1339/SeaIce/NSIDC/G02202_V4/north/daily"),
                 nsidc_cell_area_south = Path("/g/data/gv90/da1339/SeaIce/NSIDC/NSIDC0771/NSIDC0771_CellArea_PS_S25km_v1.1.nc"),
                 nsidc_cell_area_north = Path("/g/data/gv90/da1339/SeaIce/NSIDC/NSIDC0771/NSIDC0771_CellArea_PS_N25km_v1.1.nc"),
                 output_dir            = Path("./figures"),
                 animation_dir         = Path("./animations"),
                 sic_threshold         = 0.15)
```

## Core methods

### Daily CICE access

- `load_cice_day(date_str)`
- `cice_corrected_datestr(obj)`
- `pygmt_cice_da_prep(da, ...)`

### CICE diagnostics

- `compute_cice_ice_extent(ds, ...)`
- `compute_cice_area_volume_thickness(ds, ...)`
- `format_cice_ice_extent_label(...)`
- `format_cice_aggregate_sit_label(...)`

### Daily NSIDC access and diagnostics

- `find_nsidc_daily_file(date_str, hemisphere="south")`
- `load_nsidc_day(path)`
- `get_nsidc_cell_area(hemisphere)`
- `compute_nsidc_day_metrics(date_str, hemisphere=...)`
- `nsidc_sic_contour_segments(ds, hemisphere=...)`

### Figure generation

- `plot_aice_day(date_str, ...)`
- `plot_hi_day(date_str, ...)`
- `add_sia_timeseries_panel(fig, ...)`

### Animation

- `render_frames(dt0_str, dtN_str, variable="aice", ...)`
- `create_animation(dt0_str, dtN_str, variable="aice", fps=4, codec="gif")`

## Example: annotate daily concentration

```python
tb     = cice_basics()
ds     = tb.load_cice_day("1993-04-24")
dt_str = tb.cice_corrected_datestr(ds)
ext    = tb.compute_cice_ice_extent(ds)
print(dt_str)
print(ext["south"], ext["north"], ext["units"])
```

## Example: aggregate hemispheric thickness

```python
tb    = cice_basics()
ds    = tb.load_cice_day("1993-04-24")
stats = tb.compute_cice_area_volume_thickness(ds)
print("SH aggregate SIT:", stats["south"]["SIT"], stats["SIT_units"])
print("NH aggregate SIT:", stats["north"]["SIT"], stats["SIT_units"])
```

## Example: build an animation

```python
tb = cice_basics()
tb.create_animation(dt0_str            = "1993-04-01",
                    dtN_str            = "1993-04-30",
                    variable           = "aice",
                    add_sia_timeseries = True,
                    fps                = 4,
                    codec              = "gif")
```

## Assumptions

The current implementation assumes:

- CICE variables are read directly from daily `iceh.*.nc` output
- CICE time coordinates are offset by +1 day and should be corrected by subtracting one day
- `aice`, `hi`, `tarea`, and `TLAT` are present in the native CICE files
- NSIDC daily concentration files are available locally
- official NSIDC0771 cell-area NetCDFs are available for each hemisphere

## Suggested next additions

Natural extensions for the repository would be:

- a package-style layout with `pyproject.toml`
- a dedicated `examples/` directory
- small test utilities for metric sanity checks
- optional command-line wrappers for daily figures and animations
- a notebook gallery with separate `aice`, `hi`, and timeseries examples

## Notebook example

A companion notebook is provided as:

- `mawsons-chest_example.ipynb`

This notebook shows:

- class import and initialisation
- corrected-date handling
- CICE extent and aggregate thickness diagnostics
- daily `aice` and `hi` figure generation
- optional animation creation
