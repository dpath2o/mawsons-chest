from __future__ import annotations

from dataclasses import dataclass
import xarray as xr

from floes.config import FloesConfig
from floes.io.gadi import open_product


@dataclass
class ERA5Reader:
    """Minimal ERA5 reader scaffold for wind/SIE and surface-field figures."""

    config: FloesConfig
    product_key: str = "era5_monthly_surface"

    def open(self) -> xr.Dataset:
        return open_product(self.product_key, base=self.config.gadi_base, chunks=self.config.chunks, strict=True)

    def wind_speed(self, *, u_name: str = "u10", v_name: str = "v10") -> xr.DataArray:
        ds = self.open()
        if u_name not in ds or v_name not in ds:
            raise KeyError(f"Could not find {u_name!r}/{v_name!r} in ERA5 dataset: {list(ds.data_vars)}")
        wspd = (ds[u_name] ** 2 + ds[v_name] ** 2) ** 0.5
        wspd.name = "wind_speed"
        wspd.attrs.update({"long_name": "10 m wind speed", "units": ds[u_name].attrs.get("units", "m s-1")})
        return wspd
