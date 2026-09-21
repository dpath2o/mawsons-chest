from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd
import xarray as xr

from floes.config import FloesConfig

from .gridded import attach_lon_lat_from_cf_projection, cell_area_from_xy
from .sea_ice import compute_sia_sie, ensure_time_dim, resolve_year_month, select_year_month, standardise_sic


_DATE_RE = re.compile(r"(\d{8})")


@dataclass
class BremenSeaIceReader:
    """Read University of Bremen ASI-AMSR2 daily Antarctic SIC."""

    config: FloesConfig
    resolution: str = "s6250"

    @property
    def root(self) -> Path:
        return (
            Path(self.config.seaice_root)
            / "University_Bremen"
            / "AMSR2"
            / "asi_daygrid_swath"
            / self.resolution
        )

    def available_files(self) -> list[Path]:
        return sorted(self.root.glob("netcdf/*/*.nc"))

    @staticmethod
    def _ensure_file_time(ds: xr.Dataset) -> xr.Dataset:
        if any(name in ds.dims or name in ds.coords for name in ("time", "date", "t")):
            return ensure_time_dim(ds)
        source = Path(ds.encoding.get("source", "")).name
        match = _DATE_RE.search(source)
        if not match:
            raise ValueError(f"Cannot infer Bremen observation date from {source!r}")
        return ds.expand_dims(time=[pd.Timestamp(match.group(1))])

    def open_dataset(self) -> xr.Dataset:
        files = self.available_files()
        if not files:
            raise FileNotFoundError(f"No University of Bremen AMSR2 netCDF files found under {self.root}")
        return xr.open_mfdataset(
            [str(path) for path in files],
            preprocess=self._ensure_file_time,
            chunks=self.config.chunks,
            combine="by_coords",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            decode_timedelta=False,
        )

    def sic(self) -> xr.DataArray:
        ds = self.open_dataset()
        name = next(
            (
                candidate
                for candidate in (
                    "sea_ice_concentration",
                    "ice_conc",
                    "sic",
                    "ASI Ice Concentration",
                    "z",
                )
                if candidate in ds
            ),
            None,
        )
        if name is None:
            raise KeyError(f"No recognised Bremen SIC variable; variables={list(ds.data_vars)}")
        source = ds[name]
        if name == "z" and not source.attrs.get("units"):
            source.attrs["units"] = "%"
        out = standardise_sic(source)
        out = attach_lon_lat_from_cf_projection(out, ds)
        out.name = "sic"
        out.attrs.update({"source": "University of Bremen ASI-AMSR2", "hemisphere": "SH"})
        return out

    def month(self, *, year: int, month: int, fallback_latest: bool = True) -> xr.DataArray:
        sic = self.sic()
        selected_year, selected_month, exact = resolve_year_month(sic, year, month, prefer_lte=fallback_latest)
        if not exact and not fallback_latest:
            raise ValueError(f"Bremen SIC is unavailable for {year:04d}-{month:02d}")
        out = select_year_month(sic, selected_year, selected_month)
        out.attrs.update(
            {
                "source": "University of Bremen ASI-AMSR2",
                "requested_year": int(year),
                "requested_month": int(month),
                "selected_year": selected_year,
                "selected_month": selected_month,
                "exact_requested_month": exact,
            }
        )
        return out

    def total_sia_sie(self) -> xr.Dataset:
        sic = self.sic()
        area = cell_area_from_xy(sic)
        out = compute_sia_sie(sic, area, threshold=self.config.sic_threshold)
        out.attrs.update({"source": "University of Bremen ASI-AMSR2", "hemisphere": "SH"})
        return out
