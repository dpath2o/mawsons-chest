from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from floes.config import default_config
from floes.observations.bremen import BremenSeaIceReader
from floes.observations.esa_cci import ESACCISITReader


def test_bremen_reader_builds_monthly_gridded_sic(tmp_path: Path) -> None:
    directory = (
        tmp_path
        / "University_Bremen"
        / "AMSR2"
        / "asi_daygrid_swath"
        / "s6250"
        / "netcdf"
        / "2026"
    )
    directory.mkdir(parents=True)
    for day, value in ((1, 20.0), (2, 40.0)):
        xr.Dataset(
            {
                "z": (("y", "x"), [[value, value], [value, value]], {"units": "%"}),
                "longitude": (("y", "x"), [[0.0, 1.0], [0.0, 1.0]]),
                "latitude": (("y", "x"), [[-70.0, -70.0], [-71.0, -71.0]]),
            },
            coords={"x": ("x", [0.0, 6_250.0], {"units": "m"}), "y": ("y", [0.0, 6_250.0], {"units": "m"})},
        ).to_netcdf(directory / f"asi-AMSR2-s6250-202608{day:02d}-v5.4.nc")

    reader = BremenSeaIceReader(default_config(seaice_root=tmp_path, chunks=None))
    field = reader.month(year=2026, month=8)

    assert field.shape == (2, 2)
    assert np.isclose(float(field.mean()), 0.3)
    assert "longitude" in field.coords and "latitude" in field.coords


def test_esa_cci_reader_averages_latest_l3c_sensors(tmp_path: Path) -> None:
    for sensor, value in (("sentinel3a", 1.0), ("sentinel3b", 2.0)):
        directory = tmp_path / "ESA" / "CCI" / "thickness" / "L3C" / sensor / "v4.0" / "SH" / "2024"
        directory.mkdir(parents=True)
        xr.Dataset(
            {
                "sea_ice_thickness": (("y", "x"), [[value, value], [value, value]], {"units": "m"}),
                "longitude": (("y", "x"), [[0.0, 1.0], [0.0, 1.0]]),
                "latitude": (("y", "x"), [[-70.0, -70.0], [-71.0, -71.0]]),
            }
        ).to_netcdf(
            directory
            / f"ESACCI-SEAICE-L3C-SITHICK-SRAL_{sensor.upper()}-SH_50KM_EASE2-202404-fv4p0.nc"
        )

    reader = ESACCISITReader(default_config(seaice_root=tmp_path, chunks=None))
    field = reader.month(year=2026, month=8)

    assert field.attrs["selected_year"] == 2024
    assert field.attrs["selected_month"] == 4
    assert np.isclose(float(field.mean()), 1.5)
