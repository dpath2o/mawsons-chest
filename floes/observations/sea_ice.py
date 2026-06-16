from __future__ import annotations
from calendar import monthrange
import numpy as np
import pandas as pd
import xarray as xr

_TIME_NAMES = ("time", "valid_time", "date", "time_counter", "t")

def find_time_name(obj: xr.Dataset | xr.DataArray) -> str:
    """Return the best available time dimension/coordinate name."""
    for name in _TIME_NAMES:
        if name in obj.dims:
            return name
    for name in _TIME_NAMES:
        if name in obj.coords:
            return name
    raise ValueError(f"Could not infer a time coordinate from dims={obj.dims} coords={list(obj.coords)}")

def ensure_time_dim(obj: xr.Dataset | xr.DataArray) -> xr.Dataset | xr.DataArray:
    """Return ``obj`` with the primary time dimension named ``time``."""
    name = find_time_name(obj)
    out = obj
    if name != "time" and name in out.dims:
        out = out.rename({name: "time"})
    elif name != "time" and name in out.coords and "time" not in out.coords:
        out = out.rename({name: "time"})
    if "time" in out.coords:
        try:
            out = out.assign_coords(time=pd.to_datetime(out["time"].values))
        except Exception:
            pass
    return out

def standardise_sic(sic: xr.DataArray) -> xr.DataArray:
    """Return sea-ice concentration as fraction [0, 1] with invalid flags masked."""
    out = ensure_time_dim(sic) if any(n in sic.dims or n in sic.coords for n in _TIME_NAMES) else sic
    out = out.astype("float32")
    units = str(out.attrs.get("units", "")).lower()
    valid_max = out.attrs.get("valid_max", out.attrs.get("actual_range", None))
    looks_percent = "%" in units or "percent" in units
    if valid_max is not None:
        try:
            vmax = float(np.asarray(valid_max).ravel()[-1])
            looks_percent = looks_percent or vmax > 2.0
        except Exception:
            pass
    if looks_percent:
        out = out / 100.0
    out = out.where((out >= 0.0) & (out <= 1.0))
    out.name = sic.name or "sic"
    out.attrs.update({"long_name": "sea ice concentration", "units": "1"})
    return out

def compute_sia_sie(sic: xr.DataArray, area: xr.DataArray | float, *,
                    threshold: float = 0.15,
                    spatial_dims: tuple[str, str] | None = None) -> xr.Dataset:
    """Compute sea-ice area and extent time series in 10^6 km^2."""
    sic = standardise_sic(sic)
    if isinstance(area, xr.DataArray):
        units = str(area.attrs.get("units", "")).lower()
        try:
            large = float(area.max(skipna=True)) > 10_000
        except Exception:
            large = True
        area_mkm2 = area.astype("float64") * 1.0e-12 if ("m2" in units or "m^2" in units or large) else area
    else:
        area_mkm2 = area * 1.0e-12 if area > 10_000 else area
    if spatial_dims is None:
        spatial_dims = tuple(d for d in sic.dims if d != "time")
    if not spatial_dims:
        raise ValueError("No spatial dimensions found for SIA/SIE computation.")
    sia = (sic * area_mkm2).sum(dim=spatial_dims, skipna=True)
    sie = ((sic >= threshold).astype("float32") * area_mkm2).sum(dim=spatial_dims, skipna=True)
    sia.name = "SIA"
    sie.name = "SIE"
    sia.attrs.update({"long_name": "sea ice area", "units": "10^6 km^2"})
    sie.attrs.update({"long_name": "sea ice extent", "units": "10^6 km^2", "threshold": threshold})
    return xr.Dataset({"SIA": sia, "SIE": sie})

def monthly_climatology(da: xr.DataArray, *, start_year: int, end_year: int) -> xr.DataArray:
    """Return month-of-year climatology over an inclusive year window."""
    da = ensure_time_dim(da)
    clim = da.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31")).groupby("time.month").mean("time", skipna=True)
    clim.attrs.update(da.attrs)
    clim.attrs["climatology_start"] = start_year
    clim.attrs["climatology_end"] = end_year
    return clim

def monthly_anomaly(da: xr.DataArray, clim: xr.DataArray) -> xr.DataArray:
    """Return monthly anomalies using a month-of-year climatology."""
    da = ensure_time_dim(da)
    anom = da.groupby("time.month") - clim
    anom.name = f"{da.name or 'field'}_anom"
    anom.attrs.update(da.attrs)
    anom.attrs["long_name"] = f"{da.attrs.get('long_name', da.name or 'field')} anomaly"
    return anom

def available_year_months(da: xr.DataArray) -> list[tuple[int, int]]:
    """Return sorted unique (year, month) pairs present in a DataArray."""
    da = ensure_time_dim(da)
    if "time" not in da.coords or da.sizes.get("time", 0) == 0:
        return []
    t = pd.to_datetime(da["time"].values)
    pairs = sorted({(int(v.year), int(v.month)) for v in t if not pd.isna(v)})
    return pairs

def resolve_year_month(da: xr.DataArray, year: int, month: int, *, prefer_lte: bool = True) -> tuple[int, int, bool]:
    """Resolve a requested month to an available month."""
    pairs = available_year_months(da)
    if not pairs:
        raise ValueError("No valid time records are available in this product.")
    requested = (int(year), int(month))
    if requested in pairs:
        return requested[0], requested[1], True
    candidates = [p for p in pairs if p <= requested] if prefer_lte else []
    if not candidates:
        candidates = pairs
    y, m = max(candidates)
    return y, m, False

def select_year_month(da: xr.DataArray, year: int, month: int) -> xr.DataArray:
    """Select and average one calendar month from a DataArray."""
    da = ensure_time_dim(da)
    last_day = monthrange(int(year), int(month))[1]
    target = da.sel(time=slice(f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last_day:02d}"))
    if target.sizes.get("time", 0) == 0:
        target = da.where((da["time"].dt.year == year) & (da["time"].dt.month == month), drop=True)
    if target.sizes.get("time", 0) == 0:
        raise ValueError(f"No data found for {year:04d}-{month:02d}")
    out = target.mean("time", skipna=True)
    out.attrs["selected_year"] = int(year)
    out.attrs["selected_month"] = int(month)
    return out
