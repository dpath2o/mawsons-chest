from __future__ import annotations

import numpy as np
import xarray as xr


def standardise_sic(sic: xr.DataArray) -> xr.DataArray:
    """Return sea-ice concentration as fraction [0, 1] with invalid flags masked."""
    out = sic.astype("float32")
    # NSIDC CDR products are usually 0..1 after xarray scale/offset decoding;
    # if a percent product is encountered, convert defensively.
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


def compute_sia_sie(
    sic: xr.DataArray,
    area: xr.DataArray | float,
    *,
    threshold: float = 0.15,
    spatial_dims: tuple[str, str] | None = None,
) -> xr.Dataset:
    """Compute sea-ice area and extent time series.

    Parameters
    ----------
    sic
        Sea-ice concentration fraction [0, 1].
    area
        Grid-cell area in square metres or already in million km2. If an xarray
        DataArray has units mentioning ``m2`` or ``m^2``, it is converted to
        million km2.
    threshold
        Concentration threshold for extent.
    spatial_dims
        Optional explicit spatial dimensions. If omitted, all non-time dimensions
        are summed.
    """
    sic = standardise_sic(sic)
    if isinstance(area, xr.DataArray):
        units = str(area.attrs.get("units", "")).lower()
        area_mkm2 = area.astype("float64") * 1.0e-12 if ("m2" in units or "m^2" in units or float(area.max()) > 10_000) else area
    else:
        # Numeric fallback: assume square metres if large, million km2 if small.
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
    clim = da.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31")).groupby("time.month").mean("time", skipna=True)
    clim.attrs.update(da.attrs)
    clim.attrs["climatology_start"] = start_year
    clim.attrs["climatology_end"] = end_year
    return clim


def monthly_anomaly(da: xr.DataArray, clim: xr.DataArray) -> xr.DataArray:
    """Return monthly anomalies using a month-of-year climatology."""
    anom = da.groupby("time.month") - clim
    anom.name = f"{da.name or 'field'}_anom"
    anom.attrs.update(da.attrs)
    anom.attrs["long_name"] = f"{da.attrs.get('long_name', da.name or 'field')} anomaly"
    return anom


def select_year_month(da: xr.DataArray, year: int, month: int) -> xr.DataArray:
    target = da.sel(time=slice(f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-28"))
    if target.sizes.get("time", 0) == 0:
        # calendar-safe broad fallback
        target = da.where((da["time"].dt.year == year) & (da["time"].dt.month == month), drop=True)
    if target.sizes.get("time", 0) == 0:
        raise ValueError(f"No data found for {year:04d}-{month:02d}")
    return target.mean("time", skipna=True)
