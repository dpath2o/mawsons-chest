from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
import xarray as xr

from floes.config import FloesConfig
from floes.io.gadi import find_product_files, open_product

from .gridded import attach_dataset_coordinates
from .sea_ice import (
    compute_sia_sie,
    ensure_time_dim,
    mask_months,
    monthly_climatology,
    resolve_year_month,
    select_year_month,
    standardise_sic,
)


_DAILY_VERSION_RE = re.compile(r"_(\d{4})(?:_v(\d+)r(\d+))?\.nc$")
_AGGREGATE_RE = re.compile(
    r"sic_(ps[ns]25)_(\d{6}|\d{8})-(\d{6}|\d{8})_v(\d+)r(\d+)\.nc$"
)


def prefer_latest_daily_versions(files: list[Path]) -> list[Path]:
    """Keep the highest NSIDC version/revision for each year.

    The shared archive currently contains both v02r00 and v04r00 for 2024;
    opening both would duplicate every 2024 timestamp.
    """
    selected: dict[int, tuple[tuple[int, int], Path]] = {}
    for path in files:
        match = _DAILY_VERSION_RE.search(path.name)
        if not match:
            continue
        year = int(match.group(1))
        version = int(match.group(2)) if match.group(2) is not None else -1
        revision = int(match.group(3)) if match.group(3) is not None else -1
        key = (version, revision)
        if year not in selected or key > selected[year][0]:
            selected[year] = (key, path)
    return sorted(item[1] for item in selected.values())


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
        files = self._monthly_aggregate_files()
        if files:
            return files
        files = self._daily_aggregate_files()
        if files:
            return files
        return find_product_files(self.product_key, base=self.config.gadi_base, strict=False)

    def open_sic_dataset(self) -> xr.Dataset:
        files = self._monthly_aggregate_files()
        if files:
            return self._open_files(files)
        files = self._daily_aggregate_files()
        if files:
            return self._open_files(files)
        return open_product(self.product_key, base=self.config.gadi_base, chunks=self.config.chunks, strict=True)

    @property
    def _grid(self) -> str:
        return "pss25" if self.hemisphere == "SH" else "psn25"

    @property
    def _hemi_directory(self) -> str:
        return "south" if self.hemisphere == "SH" else "north"

    def _version_roots(self) -> list[Path]:
        root = Path(self.config.seaice_root) / "NSIDC"
        return sorted(root.glob("G02202_V*"), reverse=True)

    def _aggregate_candidates(self, digits: int) -> list[Path]:
        candidates: list[Path] = []
        for root in self._version_roots():
            directory = root / self._hemi_directory / "aggregate"
            candidates.extend(directory.glob(f"sic_{self._grid}_{'?' * digits}-{'?' * digits}_v*r*.nc"))
        return sorted(set(candidates))

    def _monthly_aggregate_files(self) -> list[Path]:
        """Return only the newest cumulative monthly aggregate.

        Older cumulative files overlap the newest file and must not be passed
        together to ``open_mfdataset``.
        """
        candidates = self._aggregate_candidates(6)
        ranked: list[tuple[tuple[int, int, int], Path]] = []
        for path in candidates:
            match = _AGGREGATE_RE.fullmatch(path.name)
            if match:
                ranked.append(((int(match.group(3)), int(match.group(4)), int(match.group(5))), path))
        return [max(ranked, key=lambda item: item[0])[1]] if ranked else []

    def _daily_aggregate_files(self) -> list[Path]:
        """Return the newest non-overlapping daily aggregate for each start year."""
        selected: dict[int, tuple[tuple[int, int, int], Path]] = {}
        for path in self._aggregate_candidates(8):
            match = _AGGREGATE_RE.fullmatch(path.name)
            if not match:
                continue
            start = int(match.group(2))
            key = (int(match.group(3)), int(match.group(4)), int(match.group(5)))
            year = start // 10_000
            if year not in selected or key > selected[year][0]:
                selected[year] = (key, path)
        return [selected[year][1] for year in sorted(selected)]

    def _open_files(self, files: list[Path]) -> xr.Dataset:
        return xr.open_mfdataset(
            [str(path) for path in files],
            chunks=self.config.chunks,
            combine="by_coords",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            join="outer",
            decode_timedelta=False,
        )

    def open_area(self) -> xr.DataArray:
        ancillary = self._ancillary_files()
        if ancillary:
            ds = xr.open_dataset(sorted(ancillary)[-1], chunks=None, decode_timedelta=False)
        else:
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

    def _ancillary_files(self) -> list[Path]:
        files: list[Path] = []
        for root in self._version_roots():
            files.extend(
                path
                for path in (root / self._hemi_directory / "ancillary").glob(f"*{self._grid}*.nc")
                if "invalid-ice" not in path.name
            )
        return sorted(files)

    def _attach_geographic_coords(self, da: xr.DataArray, ds: xr.Dataset) -> xr.DataArray:
        out = attach_dataset_coordinates(da, ds)
        if any(name in out.coords for name in ("longitude", "lon")) and any(
            name in out.coords for name in ("latitude", "lat")
        ):
            return out
        ancillary = self._ancillary_files()
        if not ancillary:
            return out
        coords = xr.open_dataset(ancillary[-1], chunks=None, decode_timedelta=False)
        return attach_dataset_coordinates(out, coords)

    def sic(self) -> xr.DataArray:
        ds = self.open_sic_dataset()
        for name in ("cdr_seaice_conc_monthly", "cdr_seaice_conc", "ice_conc", "seaice_conc", "sic"):
            if name in ds:
                out = standardise_sic(ds[name])
                out = self._attach_geographic_coords(out, ds)
                out.name = "sic"
                return out
        raise KeyError(f"No recognised SIC variable in NSIDC dataset: {list(ds.data_vars)}")

    def total_sia_sie(self) -> xr.Dataset:
        out = compute_sia_sie(self.sic(), self.open_area(), threshold=self.config.sic_threshold)
        out = mask_months(out)
        out.attrs.update({"source": "NSIDC CDR", "hemisphere": self.hemisphere})
        return out

    def daily_total_sia_sie(self) -> xr.Dataset:
        """Derive daily SH SIA/SIE from gridded G02202, with a legacy fallback."""
        if self.hemisphere != "SH":
            raise NotImplementedError("Only the Southern Hemisphere daily total product is registered.")
        daily_files = self._daily_aggregate_files()
        if daily_files:
            ds = self._open_files(daily_files)
            name = next(
                (
                    candidate
                    for candidate in ("cdr_seaice_conc", "ice_conc", "seaice_conc", "sic")
                    if candidate in ds
                ),
                None,
            )
            if name is None:
                raise KeyError(f"No recognised daily SIC variable in NSIDC dataset: {list(ds.data_vars)}")
            sic = self._attach_geographic_coords(standardise_sic(ds[name]), ds)
            sic = sic.sortby("time")
            _, unique = np.unique(sic["time"].values, return_index=True)
            sic = sic.isel(time=sorted(unique))
            out = compute_sia_sie(sic, self.open_area(), threshold=self.config.sic_threshold)
            out.attrs.update(
                {
                    "source": "NSIDC G02202 V6 gridded daily SIC",
                    "hemisphere": self.hemisphere,
                    "temporal_resolution": "daily",
                }
            )
            return out

        # Compatibility fallback for Will Hobbs' pre-integrated legacy files.
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
        _, files = match
        files = prefer_latest_daily_versions(files)
        ds = xr.open_mfdataset(
            [str(path) for path in files],
            chunks=self.config.chunks,
            combine="by_coords",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            decode_timedelta=False,
        )
        ds = ensure_time_dim(ds)
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
