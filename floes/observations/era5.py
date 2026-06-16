from __future__ import annotations
from dataclasses import dataclass
import xarray as xr
from floes.config import FloesConfig
from floes.io.gadi import open_product
from .sea_ice import ensure_time_dim, resolve_year_month, select_year_month

@dataclass
class ERA5Reader:
    """Minimal ERA5 reader for wind/SIE and surface-field figures."""
    config: FloesConfig
    product_key: str = "era5_monthly_surface"
    def open(self) -> xr.Dataset:
        return open_product(self.product_key, base=self.config.gadi_base, chunks=self.config.chunks, strict=True)

    def wind_speed(self, *, u_name: str = "u10", v_name: str = "v10") -> xr.DataArray:
        ds = self.open()
        # Will's processed holdings already expose mean_windspeed, which is the
        # safest product to use when raw u10/v10 are not present.
        for name in ("mean_windspeed", "wind_speed", "windspeed", "si10", "wspd", "ws"):
            if name in ds:
                da = ensure_time_dim(ds[name])
                da.name = "wind_speed"
                da.attrs.setdefault("long_name", "10 m wind speed")
                da.attrs.setdefault("units", "m s-1")
                return da
        if u_name in ds and v_name in ds:
            u = ensure_time_dim(ds[u_name])
            v = ensure_time_dim(ds[v_name])
            wspd = (u ** 2 + v ** 2) ** 0.5
            wspd.name = "wind_speed"
            wspd.attrs.update({"long_name": "10 m wind speed", "units": u.attrs.get("units", "m s-1")})
            return wspd
        raise KeyError(f"Could not find a recognised wind-speed field or {u_name!r}/{v_name!r} in ERA5 dataset: {list(ds.data_vars)}")

    def wind_speed_month(self, *, year: int, month: int, fallback_latest: bool = True) -> xr.DataArray:
        da = self.wind_speed()
        requested_year, requested_month = int(year), int(month)
        exact = True
        if fallback_latest:
            year, month, exact = resolve_year_month(da, requested_year, requested_month)
        out = select_year_month(da, year, month)
        out.attrs.update({"requested_year": requested_year,
                          "requested_month": requested_month,
                          "selected_year": int(year),
                          "selected_month": int(month),
                          "exact_requested_month": bool(exact)})
        return out
