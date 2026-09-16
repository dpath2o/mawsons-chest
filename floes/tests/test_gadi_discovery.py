from __future__ import annotations

from pathlib import Path

import pandas as pd
import xarray as xr
from floes.config import default_config
from floes.io.gadi import find_product_files
from floes.observations.era5 import ERA5Reader
from floes.observations.nsidc import NSIDCReader


def test_era5_wind_discovery_excludes_other_surface_products(tmp_path: Path) -> None:
    era5 = tmp_path / "ERA5"
    era5.mkdir()
    wind = era5 / "ERA5_sfcwind_monthly_SH_1979-2026.nc"
    tau = era5 / "ERA5_tau_monthly_SH_1979-2026.nc"
    wind.touch()
    tau.touch()

    assert find_product_files("era5_monthly_wind", base=tmp_path) == [wind]


def test_daily_nsidc_reader_falls_back_to_gadi_base(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    daily_base = tmp_path / "missing_legacy_base"
    target = primary / "NSIDC" / "moved" / "SIE_daily"
    target.mkdir(parents=True)
    path = target / "NSIDC_SH_totalSIA_daily_2026.nc"
    time = pd.date_range("2026-08-01", periods=3, freq="D")
    xr.Dataset(
        {
            "SIA_cdr": ("time", [10.0, 10.1, 10.2]),
            "SIE_cdr": ("time", [12.0, 12.1, 12.2]),
        },
        coords={"time": time},
    ).to_netcdf(path)

    reader = NSIDCReader(default_config(gadi_base=primary, chunks=None), daily_base=daily_base)
    result = reader.daily_total_sia_sie()

    assert set(result.data_vars) == {"SIA", "SIE"}
    assert result.sizes["time"] == 3
    assert result.attrs["temporal_resolution"] == "daily"


def test_daily_nsidc_reader_prefers_latest_version_per_year(tmp_path: Path) -> None:
    target = tmp_path / "NSIDC" / "SIE_daily"
    target.mkdir(parents=True)
    time = pd.date_range("2024-01-01", periods=2, freq="D")
    for version, value in (("v02r00", 2.0), ("v04r00", 4.0)):
        xr.Dataset(
            {"SIE_cdr": ("time", [value, value])},
            coords={"time": time},
        ).to_netcdf(target / f"NSIDC_SH_totalSIA_daily_2024_{version}.nc")

    result = NSIDCReader(default_config(gadi_base=tmp_path, chunks=None)).daily_total_sia_sie()

    assert result.sizes["time"] == 2
    assert float(result["SIE"].isel(time=0)) == 4.0


def _write_era5_component(root: Path, family: str, code: str, variable: str, stamp: str, value: float) -> None:
    year = stamp[:4]
    directory = root / family / "single-levels" / "reanalysis" / code / year
    directory.mkdir(parents=True, exist_ok=True)
    if family == "era5":
        end = pd.Timestamp(stamp).days_in_month
        filename = f"{code}_{family}_oper_sfc_{stamp}-{stamp[:6]}{end:02d}.nc"
    else:
        filename = f"{code}_{family}_oper_sfc_{stamp}-{stamp}.nc"
    xr.Dataset(
        {variable: (("time", "latitude", "longitude"), [[[value], [value]]])},
        coords={
            "time": [pd.Timestamp(stamp)],
            "latitude": [-90.0, -45.0],
            "longitude": [0.0],
        },
    ).to_netcdf(directory / filename)


def test_era5_reader_uses_era5t_for_current_month_and_final_when_available(tmp_path: Path) -> None:
    for family, stamp, uvalue in (("era5t", "20260801", 3.0), ("era5", "20260701", 6.0), ("era5t", "20260701", 8.0)):
        _write_era5_component(tmp_path, family, "10u", "u10", stamp, uvalue)
        _write_era5_component(tmp_path, family, "10v", "v10", stamp, 4.0 if stamp.startswith("202608") else 8.0)

    reader = ERA5Reader(default_config(era5_root=tmp_path, chunks=None))
    august = reader.wind_speed_month(year=2026, month=8)
    july = reader.wind_speed_month(year=2026, month=7)

    assert august.attrs["source"] == "ERA5T"
    assert float(august.isel(latitude=0, longitude=0)) == 5.0
    assert july.attrs["source"] == "ERA5"
    assert float(july.isel(latitude=0, longitude=0)) == 10.0
