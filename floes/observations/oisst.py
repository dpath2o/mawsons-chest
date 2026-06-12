from __future__ import annotations

from dataclasses import dataclass
import xarray as xr

from floes.config import FloesConfig
from floes.io.gadi import open_product
from .sea_ice import ensure_time_dim, monthly_climatology, resolve_year_month, select_year_month


@dataclass
class OISSTReader:
    config: FloesConfig
    product_key: str = "oisst_monthly"

    def sst(self) -> xr.DataArray:
        ds = open_product(self.product_key, base=self.config.gadi_base, chunks=self.config.chunks, strict=True)
        for name in ("sst", "SST", "analysed_sst", "sea_surface_temperature"):
            if name in ds:
                da = ensure_time_dim(ds[name])
                da.name = "sst"
                return da
        raise KeyError(f"No recognised SST variable in OISST product: {list(ds.data_vars)}")

    def anomaly_field(self, *, year: int, month: int, fallback_latest: bool = True) -> xr.DataArray:
        sst = self.sst()
        requested_year, requested_month = int(year), int(month)
        exact = True
        if fallback_latest:
            year, month, exact = resolve_year_month(sst, requested_year, requested_month)
        clim = monthly_climatology(sst, start_year=self.config.climatology_start, end_year=self.config.climatology_end)
        out = select_year_month(sst, year, month) - clim.sel(month=month)
        out.name = "sst_anom"
        out.attrs.update({
            "long_name": "sea-surface temperature anomaly",
            "units": sst.attrs.get("units", "degC"),
            "requested_year": requested_year,
            "requested_month": requested_month,
            "selected_year": int(year),
            "selected_month": int(month),
            "exact_requested_month": bool(exact),
        })
        return out
