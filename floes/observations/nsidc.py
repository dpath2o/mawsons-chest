from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xarray as xr

from floes.config import FloesConfig
from floes.io.gadi import find_product_files, open_product
from .sea_ice import compute_sia_sie, monthly_anomaly, monthly_climatology, select_year_month, standardise_sic


@dataclass
class NSIDCReader:
    """Reader/processor for NSIDC CDR sea-ice concentration products."""

    config: FloesConfig
    product_key: str = "nsidc_cdr_sic_monthly_sh"
    area_key: str = "nsidc_cell_area_sh"

    def available_files(self) -> list[Path]:
        return find_product_files(self.product_key, base=self.config.gadi_base, strict=False)

    def open_sic_dataset(self) -> xr.Dataset:
        return open_product(self.product_key, base=self.config.gadi_base, chunks=self.config.chunks, strict=True)

    def open_area(self) -> xr.DataArray:
        ds = open_product(self.area_key, base=self.config.gadi_base, chunks=None, strict=True)
        if "cell_area" in ds:
            area = ds["cell_area"]
        else:
            # Ancillary G02202 files can differ. Prefer the first 2D area-like field.
            candidates = [v for v in ds.data_vars if "area" in v.lower()]
            if not candidates:
                raise KeyError(f"No area variable found in {self.area_key}; variables={list(ds.data_vars)}")
            area = ds[candidates[0]]
        area.attrs.setdefault("units", "m2")
        return area

    def sic(self) -> xr.DataArray:
        ds = self.open_sic_dataset()
        for name in ("cdr_seaice_conc_monthly", "cdr_seaice_conc", "ice_conc", "seaice_conc"):
            if name in ds:
                out = standardise_sic(ds[name])
                out.name = "sic"
                return out
        raise KeyError(f"No recognised SIC variable in NSIDC dataset: {list(ds.data_vars)}")

    def total_sia_sie(self) -> xr.Dataset:
        return compute_sia_sie(self.sic(), self.open_area(), threshold=self.config.sic_threshold)

    def sic_month_and_climatology(self, *, year: int, month: int) -> xr.Dataset:
        sic = self.sic()
        clim = monthly_climatology(
            sic,
            start_year=self.config.climatology_start,
            end_year=self.config.climatology_end,
        )
        month_field = select_year_month(sic, year, month)
        clim_field = clim.sel(month=month)
        anom = month_field - clim_field
        anom.name = "sic_anom"
        anom.attrs.update({
            "long_name": "sea ice concentration anomaly",
            "units": "1",
            "year": year,
            "month": month,
            "climatology_start": self.config.climatology_start,
            "climatology_end": self.config.climatology_end,
        })
        return xr.Dataset({"sic": month_field, "sic_clim": clim_field, "sic_anom": anom})
