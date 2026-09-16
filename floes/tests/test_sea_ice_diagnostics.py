from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr
from floes.observations.sea_ice import (
    annual_mean_complete,
    annual_sie_maximum,
    mask_months,
    monthly_anomalies,
    standardised_monthly_anomalies,
    year_month_matrix,
)


def _monthly_series(start: str = "1979-01-01", end: str = "1982-12-01") -> xr.DataArray:
    time = pd.date_range(start, end, freq="MS")
    values = np.arange(time.size, dtype=float)
    return xr.DataArray(values, coords={"time": time}, dims="time", name="SIE")


def test_monthly_anomalies_are_zero_mean_over_reference() -> None:
    series = _monthly_series()
    anomaly = monthly_anomalies(series, start_year=1979, end_year=1981)
    reference = anomaly.sel(time=slice("1979-01-01", "1981-12-31"))
    np.testing.assert_allclose(reference.groupby("time.month").mean("time"), 0.0)


def test_standardised_anomalies_have_unit_sample_std_over_reference() -> None:
    series = _monthly_series()
    anomaly = standardised_monthly_anomalies(series, start_year=1979, end_year=1981)
    reference = anomaly.sel(time=slice("1979-01-01", "1981-12-31"))
    np.testing.assert_allclose(reference.groupby("time.month").std("time", ddof=1), 1.0)


def test_mask_months_preserves_axis_and_masks_known_gap() -> None:
    series = _monthly_series("1987-11-01", "1988-02-01")
    masked = mask_months(series)
    assert masked.sizes["time"] == 4
    assert bool(masked.sel(time="1987-11-01").notnull())
    assert bool(masked.sel(time="1987-12-01").isnull())
    assert bool(masked.sel(time="1988-01-01").isnull())
    assert bool(masked.sel(time="1988-02-01").notnull())


def test_annual_mean_requires_twelve_valid_months() -> None:
    series = _monthly_series("2000-01-01", "2001-12-01")
    series.loc[{"time": "2001-06-01"}] = np.nan
    annual = annual_mean_complete(series)
    assert bool(annual.sel(year=2000).notnull())
    assert bool(annual.sel(year=2001).isnull())


def test_year_month_matrix_retains_partial_current_year() -> None:
    series = _monthly_series("2025-01-01", "2026-08-01")
    matrix = year_month_matrix(series)
    assert matrix.sizes == {"year": 2, "month": 12}
    assert bool(matrix.sel(year=2026, month=8).notnull())
    assert bool(matrix.sel(year=2026, month=9).isnull())


def test_annual_sie_maximum_reports_smoothed_peak_date() -> None:
    time = pd.date_range("2024-08-01", "2024-10-31", freq="D")
    values = np.zeros(time.size)
    peak = int(np.flatnonzero(time == pd.Timestamp("2024-09-15"))[0])
    values[peak - 2 : peak + 3] = 10.0
    series = xr.DataArray(values, coords={"time": time}, dims="time", name="SIE")
    result = annual_sie_maximum(series)
    assert float(result["SIE_max"].sel(year=2024)) == 10.0
    assert int(result["day_of_max"].sel(year=2024)) == pd.Timestamp("2024-09-15").dayofyear
    assert result.attrs["data_end"] == "2024-10-31"
