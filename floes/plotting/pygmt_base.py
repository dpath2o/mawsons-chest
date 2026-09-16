from __future__ import annotations
from pathlib import Path
import numpy as np
import xarray as xr

def require_pygmt():
    try:
        import pygmt
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("PyGMT/GMT is required for floes plotting. Load a Gadi environment with pygmt before running.") from exc
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


def has_curvilinear_lon_lat(da: xr.DataArray) -> bool:
    """Return True when ``da`` carries two-dimensional lon/lat coordinates."""
    lon, lat = infer_lon_lat(da)
    return lon is not None and lat is not None and lon.ndim == 2 and lat.ndim == 2

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


def _bilinear_sample(field: np.ndarray, x: np.ndarray, y: np.ndarray, *, circular: bool = False) -> np.ndarray:
    """Sample a two-dimensional field at fractional array indices."""
    ny, nx = field.shape
    x = np.clip(np.asarray(x, dtype=float), 0.0, nx - 1.0)
    y = np.clip(np.asarray(y, dtype=float), 0.0, ny - 1.0)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    x1 = np.minimum(x0 + 1, nx - 1)
    y1 = np.minimum(y0 + 1, ny - 1)
    wx = x - x0
    wy = y - y0

    values = np.asarray(field, dtype=float)
    if circular:
        values = np.exp(1j * np.deg2rad(values))
    sampled = (
        values[y0, x0] * (1.0 - wx) * (1.0 - wy)
        + values[y0, x1] * wx * (1.0 - wy)
        + values[y1, x0] * (1.0 - wx) * wy
        + values[y1, x1] * wx * wy
    )
    if circular:
        sampled = np.rad2deg(np.angle(sampled))
    return np.asarray(sampled)


def curvilinear_contour_segments(da: xr.DataArray, level: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """Extract a contour as dateline-safe lon/lat segments.

    Contouring is performed in array-index space, then the vertices are mapped
    onto the two-dimensional geographic coordinates. This avoids PyGMT treating
    the NSIDC polar-stereographic x/y indices as longitude and latitude.
    """
    lon, lat = infer_lon_lat(da)
    if lon is None or lat is None or lon.ndim != 2 or lat.ndim != 2:
        raise ValueError("A two-dimensional longitude/latitude grid is required.")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    values = np.ma.masked_invalid(np.asarray(da.squeeze().values, dtype=float))
    figure, axis = plt.subplots()
    contour = axis.contour(values, levels=[level])
    index_segments = contour.allsegs[0]
    plt.close(figure)

    output: list[tuple[np.ndarray, np.ndarray]] = []
    lon_values = np.asarray(lon.squeeze().values, dtype=float)
    lat_values = np.asarray(lat.squeeze().values, dtype=float)
    for vertices in index_segments:
        if len(vertices) < 2:
            continue
        x = vertices[:, 0]
        y = vertices[:, 1]
        seg_lon = _bilinear_sample(lon_values, x, y, circular=True)
        seg_lat = _bilinear_sample(lat_values, x, y)
        finite = np.isfinite(seg_lon) & np.isfinite(seg_lat)
        breaks = np.flatnonzero((~finite[1:]) | (~finite[:-1]) | (np.abs(np.diff(seg_lon)) > 180.0)) + 1
        for indices in np.split(np.arange(len(seg_lon)), breaks):
            indices = indices[finite[indices]]
            if indices.size >= 2:
                output.append((seg_lon[indices], seg_lat[indices]))
    return output


def plot_geographic_contour(fig, da: xr.DataArray, *, level: float, pen: str) -> None:
    """Plot a contour correctly for either regular or curvilinear coordinates."""
    if has_curvilinear_lon_lat(da):
        for longitude, latitude in curvilinear_contour_segments(da, level):
            fig.plot(x=longitude, y=latitude, pen=pen)
    else:
        fig.grdcontour(grid=da.squeeze(), levels=[level], annotation="n", pen=pen)

def add_coast_grid(frame, *, region=None, projection=None, land="gray85", water="white", shorelines="0.25p,black"):
    frame.coast(region=region, projection=projection, land=land, water=water, shorelines=shorelines, frame="afg")
