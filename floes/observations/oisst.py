from __future__ import annotations

from dataclasses import dataclass
import xarray as xr

from floes.config import FloesConfig
from floes.io.gadi import open_product
from .sea_ice import monthly_climatology, select_year_month


@dataclass
class OISSTReader:
    config: FloesConfig
    product_key: str = "oisst_monthly"

    def sst(self) -> xr.DataArray:
        ds = open_product(self.product_key, base=self.config.gadi_base, chunks=self.config.chunks, strict=True)
        if "sst" not in ds:
            raise KeyError(f"No 'sst' variable in OISST product: {list(ds.data_vars)}")
        return ds["sst"]

    def anomaly_field(self, *, year: int, month: int) -> xr.DataArray:
        sst = self.sst()
        clim = monthly_climatology(sst, start_year=self.config.climatology_start, end_year=self.config.climatology_end)
        out = select_year_month(sst, year, month) - clim.sel(month=month)
        out.name = "sst_anom"
        out.attrs.update({"long_name": "sea-surface temperature anomaly", "units": sst.attrs.get("units", "degC")})
        return out
