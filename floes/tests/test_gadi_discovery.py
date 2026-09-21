from __future__ import annotations

from pathlib import Path

import numpy as np
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


def test_nsidc_reader_prefers_gridded_g02202_archive(tmp_path: Path) -> None:
    root = tmp_path / "SeaIce"
    version = root / "NSIDC" / "G02202_V6" / "south"
    aggregate = version / "aggregate"
    ancillary = version / "ancillary"
    aggregate.mkdir(parents=True)
    ancillary.mkdir(parents=True)
    longitude = [[0.0, 1.0], [0.0, 1.0]]
    latitude = [[-70.0, -70.0], [-71.0, -71.0]]
    xr.Dataset(
        {
            "cdr_seaice_conc_monthly": (
                ("time", "y", "x"),
                [[[0.0, 0.5], [1.0, 0.2]]],
                {"units": "1"},
            ),
            "longitude": (("y", "x"), longitude),
            "latitude": (("y", "x"), latitude),
        },
        coords={"time": [pd.Timestamp("2026-08-01")]},
    ).to_netcdf(aggregate / "sic_pss25_197811-202608_v06r00.nc")
    xr.Dataset(
        {
            "cdr_seaice_conc": (
                ("time", "y", "x"),
                [[[0.0, 0.5], [1.0, 0.2]], [[0.0, 0.0], [1.0, 0.0]]],
                {"units": "1"},
            ),
            "longitude": (("y", "x"), longitude),
            "latitude": (("y", "x"), latitude),
        },
        coords={"time": pd.date_range("2026-08-01", periods=2, freq="D")},
    ).to_netcdf(aggregate / "sic_pss25_20260101-20260802_v06r00.nc")
    xr.Dataset(
        {"cell_area": (("y", "x"), [[1.0e6, 1.0e6], [1.0e6, 1.0e6]], {"units": "m2"})}
    ).to_netcdf(ancillary / "G02202-ancillary-pss25-v06r00.nc")

    reader = NSIDCReader(default_config(seaice_root=root, gadi_base=tmp_path / "unused", chunks=None))
    sic = reader.sic()
    daily = reader.daily_total_sia_sie()

    assert sic.sizes["time"] == 1
    assert "longitude" in sic.coords and "latitude" in sic.coords
    assert daily.sizes["time"] == 2
    assert np.isclose(float(daily["SIE"].isel(time=0)), 3.0e-6)


def _write_era5_component(root: Path, family: str, code: str, variable: str, stamp: str, value: float) -> None:
    year = stamp[:4]
    directory = root / family / "single-levels" / "reanalysis" / code / year
    directory.mkdir(parents=True, exist_ok=True)
    if family == "era5":
        end = pd.Timestamp(stamp).days_in_month
        filename = f"{code}_{family}_oper_sfc_{stamp}-{stamp[:6]}{end:02d}.nc"
    else:
        filename = f"{code}_{family}_oper_sfc_{stamp}-{stamp}.nc"
    data = xr.DataArray(
        [[[value], [value]]],
        dims=("time", "latitude", "longitude"),
        attrs={"units": "Pa" if variable == "msl" else "m s-1"},
    )
    xr.Dataset(
        {variable: data},
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
        _write_era5_component(tmp_path, family, "msl", "msl", stamp, 100_000.0)

    reader = ERA5Reader(default_config(era5_root=tmp_path, chunks=None))
    august = reader.wind_speed_month(year=2026, month=8)
    july = reader.wind_speed_month(year=2026, month=7)

    assert august.attrs["source"] == "ERA5T"
    assert float(august.isel(latitude=0, longitude=0)) == 5.0
    assert july.attrs["source"] == "ERA5"
    assert float(july.isel(latitude=0, longitude=0)) == 10.0

    august_fields = reader.wind_mslp_month(year=2026, month=8)
    assert august_fields.attrs["source"] == "ERA5T"
    assert set(august_fields.data_vars) == {"wind_speed", "mslp"}
    assert float(august_fields["mslp"].isel(latitude=0, longitude=0)) == 1000.0
