from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import xarray as xr

from floes.config import FloesConfig
from floes.io.gadi import find_product_files, open_product

from .sea_ice import (
    compute_sia_sie,
    ensure_time_dim,
    mask_months,
    monthly_climatology,
    resolve_year_month,
    select_year_month,
    standardise_sic,
)


@dataclass
class NSIDCReader:
    """Reader/processor for NSIDC CDR sea-ice concentration products."""

    config: FloesConfig
    hemisphere: str = "SH"
    product_key: str | None = None
    area_key: str | None = None
    daily_base: Path | None = None

    def __post_init__(self) -> None:
        self.hemisphere = self.hemisphere.upper()
        if self.hemisphere not in {"SH", "NH"}:
            raise ValueError("hemisphere must be 'SH' or 'NH'")
        suffix = self.hemisphere.lower()
        self.product_key = self.product_key or f"nsidc_cdr_sic_monthly_{suffix}"
        self.area_key = self.area_key or f"nsidc_cell_area_{suffix}"

    def available_files(self) -> list[Path]:
        return find_product_files(self.product_key, base=self.config.gadi_base, strict=False)

    def open_sic_dataset(self) -> xr.Dataset:
        return open_product(self.product_key, base=self.config.gadi_base, chunks=self.config.chunks, strict=True)

    def open_area(self) -> xr.DataArray:
        ds = open_product(self.area_key, base=self.config.gadi_base, chunks=None, strict=True)
        if "cell_area" in ds:
            area = ds["cell_area"]
        else:
            candidates = [v for v in ds.data_vars if "area" in v.lower()]
            if not candidates:
                raise KeyError(f"No area variable found in {self.area_key}; variables={list(ds.data_vars)}")
            area = ds[candidates[0]]
        area.attrs.setdefault("units", "m2")
        return area

    def sic(self) -> xr.DataArray:
        ds = self.open_sic_dataset()
        for name in ("cdr_seaice_conc_monthly", "cdr_seaice_conc", "ice_conc", "seaice_conc", "sic"):
            if name in ds:
                out = standardise_sic(ds[name])
                out.name = "sic"
                return out
        raise KeyError(f"No recognised SIC variable in NSIDC dataset: {list(ds.data_vars)}")

    def total_sia_sie(self) -> xr.Dataset:
        out = compute_sia_sie(self.sic(), self.open_area(), threshold=self.config.sic_threshold)
        out = mask_months(out)
        out.attrs.update({"source": "NSIDC CDR", "hemisphere": self.hemisphere})
        return out

    def daily_total_sia_sie(self) -> xr.Dataset:
        """Open the pre-integrated daily SH SIA/SIE files used by the legacy workflow."""
        if self.hemisphere != "SH":
            raise NotImplementedError("Only the Southern Hemisphere daily total product is registered.")
        bases = []
        for base in (self.daily_base, self.config.gadi_base):
            if base is not None and Path(base) not in bases:
                bases.append(Path(base))
        files_by_base = [(base, find_product_files("nsidc_total_daily_sh", base=base, strict=False)) for base in bases]
        match = next(((base, files) for base, files in files_by_base if files), None)
        if match is None:
            searched = ", ".join(str(base) for base in bases)
            raise FileNotFoundError(
                "No pre-integrated NSIDC daily SH SIA/SIE files were found. "
                f"Searched bases: {searched}. Expected names resembling "
                "NSIDC_SH_totalSIA_daily_*.nc."
            )
        base, _ = match
        ds = ensure_time_dim(open_product("nsidc_total_daily_sh", base=base, chunks=self.config.chunks, strict=True))
        variables: dict[str, xr.DataArray] = {}
        for target, candidates in {
            "SIA": ("SIA", "SIA_cdr", "sia"),
            "SIE": ("SIE", "SIE_cdr", "sie"),
        }.items():
            name = next((candidate for candidate in candidates if candidate in ds), None)
            if name is not None:
                variables[target] = ds[name]
        if "SIE" not in variables:
            raise KeyError(f"No recognised daily SIE variable in NSIDC dataset: {list(ds.data_vars)}")
        out = xr.Dataset(variables)
        out.attrs.update({"source": "NSIDC CDR", "hemisphere": self.hemisphere, "temporal_resolution": "daily"})
        return out

    def sic_month_and_climatology(self, *, year: int, month: int, fallback_latest: bool = True) -> xr.Dataset:
        sic = self.sic()
        requested_year, requested_month = int(year), int(month)
        exact = True
        if fallback_latest:
            year, month, exact = resolve_year_month(sic, requested_year, requested_month)
        clim = monthly_climatology(sic, start_year=self.config.climatology_start, end_year=self.config.climatology_end)
        month_field = select_year_month(sic, year, month)
        clim_field = clim.sel(month=month)
        anom = month_field - clim_field
        anom.name = "sic_anom"
        common_attrs = {
            "requested_year": requested_year,
            "requested_month": requested_month,
            "selected_year": int(year),
            "selected_month": int(month),
            "exact_requested_month": bool(exact),
            "climatology_start": self.config.climatology_start,
            "climatology_end": self.config.climatology_end,
        }
        anom.attrs.update({"long_name": "sea ice concentration anomaly", "units": "1", **common_attrs})
        month_field.attrs.update(common_attrs)
        clim_field.attrs.update(common_attrs)
        return xr.Dataset({"sic": month_field, "sic_clim": clim_field, "sic_anom": anom}, attrs=common_attrs)
