from __future__ import annotations

from pathlib import Path

import pandas as pd
import xarray as xr
from floes.config import default_config
from floes.io.gadi import find_product_files
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
