from __future__ import annotations

import numpy as np
import xarray as xr


LON_NAMES = ("longitude", "lon", "nav_lon", "geolon", "TLON")
LAT_NAMES = ("latitude", "lat", "nav_lat", "geolat", "TLAT")


def attach_dataset_coordinates(da: xr.DataArray, ds: xr.Dataset) -> xr.DataArray:
    """Attach geographic coordinates held as sibling variables in ``ds``."""
    out = da
    for name in (*LON_NAMES, *LAT_NAMES):
        if name in ds and name not in out.coords:
            candidate = ds[name].squeeze()
            if set(candidate.dims).issubset(out.dims):
                out = out.assign_coords({name: candidate})
    return out


def attach_lon_lat_from_cf_projection(da: xr.DataArray, ds: xr.Dataset) -> xr.DataArray:
    """Derive two-dimensional longitude/latitude from CF x/y projection metadata.

    Bremen netCDF products are georeferenced, but some releases expose only
    projected x/y coordinates. PyGMT polar maps need explicit geographic
    coordinates, so derive them once with pyproj when necessary.
    """
    out = attach_dataset_coordinates(da, ds)
    if any(name in out.coords for name in LON_NAMES) and any(name in out.coords for name in LAT_NAMES):
        return out

    x_name = next((name for name in ("x", "xc", "xgrid") if name in out.coords), None)
    y_name = next((name for name in ("y", "yc", "ygrid") if name in out.coords), None)
    if x_name is None or y_name is None:
        return out

    mapping_name = out.attrs.get("grid_mapping")
    mapping = ds.get(mapping_name) if mapping_name else None
    if mapping is None:
        mapping = next(
            (var for var in ds.variables.values() if "grid_mapping_name" in var.attrs),
            None,
        )
    if mapping is None:
        return out

    try:
        from pyproj import CRS, Transformer

        wkt = mapping.attrs.get("crs_wkt") or mapping.attrs.get("spatial_ref")
        source = CRS.from_wkt(wkt) if wkt else CRS.from_cf(mapping.attrs)
        transformer = Transformer.from_crs(source, CRS.from_epsg(4326), always_xy=True)
        x, y = np.meshgrid(np.asarray(out[x_name].values), np.asarray(out[y_name].values))
        longitude, latitude = transformer.transform(x, y)
    except Exception:
        return out

    return out.assign_coords(
        longitude=((y_name, x_name), longitude),
        latitude=((y_name, x_name), latitude),
    )


def cell_area_from_xy(da: xr.DataArray) -> xr.DataArray:
    """Return a constant projected-grid cell area from one-dimensional x/y axes."""
    x_name = next((name for name in ("x", "xc", "xgrid") if name in da.coords), None)
    y_name = next((name for name in ("y", "yc", "ygrid") if name in da.coords), None)
    if x_name is None or y_name is None or da[x_name].size < 2 or da[y_name].size < 2:
        raise ValueError("Cannot infer cell area without one-dimensional projected x/y coordinates.")
    dx = float(np.nanmedian(np.abs(np.diff(np.asarray(da[x_name].values, dtype=float)))))
    dy = float(np.nanmedian(np.abs(np.diff(np.asarray(da[y_name].values, dtype=float)))))
    units = f"{da[x_name].attrs.get('units', '')} {da[y_name].attrs.get('units', '')}".lower()
    scale = 1.0e6 if "km" in units else 1.0
    area = xr.DataArray(dx * dy * scale, attrs={"long_name": "grid-cell area", "units": "m2"})
    return area
