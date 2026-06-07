from __future__ import annotations

from pathlib import Path
import numpy as np
import xarray as xr


def require_pygmt():
    try:
        import pygmt
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "PyGMT/GMT is required for floes plotting. Load a Gadi environment with pygmt before running."
        ) from exc
    return pygmt


def south_polar_region(latmax: float = -45.0) -> list[float]:
    return [-180.0, 180.0, -90.0, latmax]


def south_polar_projection(width: str = "16c") -> str:
    return f"S0/-90/{width}"


def infer_lon_lat(da: xr.DataArray, lon_name: str | None = None, lat_name: str | None = None) -> tuple[xr.DataArray | None, xr.DataArray | None]:
    lon_candidates = [lon_name, "lon", "longitude", "nav_lon", "geolon", "TLON"]
    lat_candidates = [lat_name, "lat", "latitude", "nav_lat", "geolat", "TLAT"]
    lon = next((da.coords[n] for n in lon_candidates if n and n in da.coords), None)
    lat = next((da.coords[n] for n in lat_candidates if n and n in da.coords), None)
    return lon, lat


def write_xyz_from_curvilinear(da: xr.DataArray, path: Path, *, lon_name: str | None = None, lat_name: str | None = None, stride: int = 1) -> Path:
    """Write lon/lat/value triples for PyGMT plotting from curvilinear grids."""
    lon, lat = infer_lon_lat(da, lon_name=lon_name, lat_name=lat_name)
    if lon is None or lat is None:
        raise ValueError("Cannot write XYZ: longitude/latitude coordinates not found.")
    arr = da.squeeze().values
    x = lon.squeeze().values
    y = lat.squeeze().values
    if stride > 1:
        arr = arr[::stride, ::stride]
        x = x[::stride, ::stride]
        y = y[::stride, ::stride]
    mask = np.isfinite(arr) & np.isfinite(x) & np.isfinite(y)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.column_stack([x[mask].ravel(), y[mask].ravel(), arr[mask].ravel()])
    np.savetxt(path, data, fmt="%.6f %.6f %.8g")
    return path


def add_coast_grid(frame, *, region=None, projection=None, land="gray85", water="white", shorelines="0.25p,black"):
    frame.coast(region=region, projection=projection, land=land, water=water, shorelines=shorelines, frame="afg")
