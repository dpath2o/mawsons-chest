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


def compute_sia_sie(
    sic: xr.DataArray,
    area: xr.DataArray | float,
    *,
    threshold: float = 0.15,
    spatial_dims: tuple[str, str] | None = None,
) -> xr.Dataset:
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
    clim = (
        da.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31")).groupby("time.month").mean("time", skipna=True)
    )
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


def monthly_anomalies(da: xr.DataArray, *, start_year: int, end_year: int) -> xr.DataArray:
    """Return monthly anomalies for an inclusive climatology window."""
    clim = monthly_climatology(da, start_year=start_year, end_year=end_year)
    out = monthly_anomaly(da, clim)
    out.attrs.update({"climatology_start": start_year, "climatology_end": end_year})
    return out


def standardised_monthly_anomalies(
    da: xr.DataArray,
    *,
    start_year: int,
    end_year: int,
    ddof: int = 1,
) -> xr.DataArray:
    """Return monthly anomalies divided by the climatological monthly standard deviation.

    ``ddof=1`` matches the sample-standard-deviation convention in the legacy NCL
    workflow. Months with zero climatological variance are returned as missing.
    """
    da = ensure_time_dim(da)
    reference = da.sel(time=slice(f"{start_year}-01-01", f"{end_year}-12-31"))
    std = reference.groupby("time.month").std("time", skipna=True, ddof=ddof)
    out = monthly_anomalies(da, start_year=start_year, end_year=end_year).groupby("time.month") / std.where(std > 0)
    out.name = f"{da.name or 'field'}_standardised_anom"
    out.attrs.update(
        {
            "long_name": f"standardised {da.attrs.get('long_name', da.name or 'field')} anomaly",
            "units": "1",
            "climatology_start": start_year,
            "climatology_end": end_year,
        }
    )
    return out


def mask_months(
    obj: xr.Dataset | xr.DataArray,
    year_months: tuple[tuple[int, int], ...] = ((1987, 12), (1988, 1)),
) -> xr.Dataset | xr.DataArray:
    """Mask known bad or missing calendar months without dropping the time axis."""
    obj = ensure_time_dim(obj)
    keep = xr.ones_like(obj["time"], dtype=bool)
    for year, month in year_months:
        keep = keep & ~((obj["time"].dt.year == year) & (obj["time"].dt.month == month))
    return obj.where(keep)


def annual_mean_complete(da: xr.DataArray, *, minimum_months: int = 12) -> xr.DataArray:
    """Return annual means only where at least ``minimum_months`` are valid."""
    da = ensure_time_dim(da)
    valid = da.notnull().groupby("time.year").sum("time")
    means = da.groupby("time.year").mean("time", skipna=True).where(valid >= minimum_months)
    means.name = f"{da.name or 'field'}_annual"
    means.attrs.update(da.attrs)
    return means


def year_month_matrix(da: xr.DataArray) -> xr.DataArray:
    """Reshape a monthly time series to ``(year, month)`` with missing months retained."""
    da = ensure_time_dim(da)
    years = np.arange(int(da["time"].dt.year.min()), int(da["time"].dt.year.max()) + 1)
    index = pd.MultiIndex.from_arrays([da["time"].dt.year.values, da["time"].dt.month.values], names=("year", "month"))
    out = da.assign_coords(year_month=("time", index)).swap_dims({"time": "year_month"}).drop_vars("time")
    out = out.unstack("year_month").reindex(year=years, month=np.arange(1, 13))
    out.name = da.name
    out.attrs.update(da.attrs)
    return out


def annual_sie_maximum(
    sie: xr.DataArray,
    *,
    start_month: int = 8,
    end_month: int = 10,
    rolling_days: int = 5,
) -> xr.Dataset:
    """Return annual smoothed SIE maxima and their day of year.

    This reproduces the legacy diagnostic: retain August--October, apply a
    centred five-sample running mean, then find each year's maximum.
    """
    sie = ensure_time_dim(sie)
    season = sie.where(sie["time"].dt.month.isin(np.arange(start_month, end_month + 1)), drop=True)
    smooth = season.rolling(time=rolling_days, min_periods=rolling_days, center=True).mean()
    years: list[int] = []
    maxima: list[float] = []
    days: list[int] = []
    dates: list[np.datetime64] = []
    for year, group in smooth.groupby("time.year"):
        values = np.asarray(group.values)
        if values.size == 0 or np.all(np.isnan(values)):
            continue
        index = int(np.nanargmax(values))
        timestamp = pd.Timestamp(group["time"].values[index])
        years.append(int(year))
        maxima.append(float(values[index]))
        days.append(int(timestamp.dayofyear))
        dates.append(timestamp.to_datetime64())
    return xr.Dataset(
        data_vars={
            "SIE_max": (
                "year",
                maxima,
                {"long_name": "annual maximum sea ice extent", "units": sie.attrs.get("units", "10^6 km^2")},
            ),
            "day_of_max": ("year", days, {"long_name": "day of annual maximum sea ice extent", "units": "day of year"}),
            "date_of_max": ("year", dates, {"long_name": "date of annual maximum sea ice extent"}),
        },
        coords={"year": years},
        attrs={
            "start_month": start_month,
            "end_month": end_month,
            "rolling_days": rolling_days,
            "data_end": str(pd.Timestamp(sie["time"].max().values).date()),
        },
    )


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
