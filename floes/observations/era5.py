from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import xarray as xr

from floes.config import FloesConfig

from .sea_ice import ensure_time_dim


_DATE_RE = re.compile(r"_(\d{8})-(\d{8})\.nc$")


@dataclass
class ERA5Reader:
    """Read final ERA5 and near-real-time ERA5T directly from ``/g/data/rt52``.

    Final ERA5 is preferred whenever the requested month is available. ERA5T is
    used only to bridge the publication lag for recent months. Historical
    climatologies should therefore be constructed from final ERA5 only.
    """

    config: FloesConfig
    latmax_sh: float = -45.0

    _COMPONENTS = {"u10": "10u", "v10": "10v"}

    def _component_files(self, family: str, name: str, year: int, month: int) -> list[Path]:
        code = self._COMPONENTS[name]
        directory = (
            Path(self.config.era5_root)
            / family
            / "single-levels"
            / "reanalysis"
            / code
            / f"{year:04d}"
        )
        pattern = f"{code}_{family}_oper_sfc_{year:04d}{month:02d}*.nc"
        return sorted(directory.glob(pattern))

    def _available_months(self, family: str, name: str) -> set[tuple[int, int]]:
        code = self._COMPONENTS[name]
        root = Path(self.config.era5_root) / family / "single-levels" / "reanalysis" / code
        months: set[tuple[int, int]] = set()
        for path in root.glob(f"*/{code}_{family}_oper_sfc_*.nc"):
            match = _DATE_RE.search(path.name)
            if match:
                stamp = match.group(1)
                months.add((int(stamp[:4]), int(stamp[4:6])))
        return months

    def _select_month(
        self, year: int, month: int, fallback_latest: bool
    ) -> tuple[str, int, int, list[Path], list[Path], bool]:
        requested = (int(year), int(month))
        for family in ("era5", "era5t"):
            ufiles = self._component_files(family, "u10", *requested)
            vfiles = self._component_files(family, "v10", *requested)
            if ufiles and vfiles:
                return family, *requested, ufiles, vfiles, True

        if not fallback_latest:
            raise FileNotFoundError(
                f"No matching ERA5/ERA5T u10 and v10 files for {year:04d}-{month:02d} "
                f"under {self.config.era5_root}"
            )

        candidates: list[tuple[tuple[int, int], int, str]] = []
        for family, priority in (("era5", 1), ("era5t", 0)):
            common = self._available_months(family, "u10") & self._available_months(family, "v10")
            candidates.extend((ym, priority, family) for ym in common if ym <= requested)
        if not candidates:
            raise FileNotFoundError(
                f"No common ERA5/ERA5T u10 and v10 month at or before {year:04d}-{month:02d} "
                f"under {self.config.era5_root}"
            )
        (selected_year, selected_month), _, family = max(candidates)
        ufiles = self._component_files(family, "u10", selected_year, selected_month)
        vfiles = self._component_files(family, "v10", selected_year, selected_month)
        return family, selected_year, selected_month, ufiles, vfiles, False

    def _open_component(self, paths: list[Path], name: str) -> xr.DataArray:
        ds = xr.open_mfdataset(
            [str(path) for path in paths],
            chunks=self.config.chunks,
            combine="by_coords",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            decode_timedelta=False,
        )
        if name not in ds:
            raise KeyError(f"Variable {name!r} not found in ERA5 files; variables={list(ds.data_vars)}")
        return ensure_time_dim(ds[name])

    def _southern_ocean(self, da: xr.DataArray) -> xr.DataArray:
        lat_name = next((name for name in ("latitude", "lat") if name in da.coords), None)
        if lat_name is None or da[lat_name].ndim != 1:
            return da
        lat = da[lat_name]
        bounds = slice(self.latmax_sh, -90.0) if float(lat[0]) > float(lat[-1]) else slice(-90.0, self.latmax_sh)
        return da.sel({lat_name: bounds})

    def wind_speed_month(self, *, year: int, month: int, fallback_latest: bool = True) -> xr.DataArray:
        requested_year, requested_month = int(year), int(month)
        family, year, month, ufiles, vfiles, exact = self._select_month(
            requested_year, requested_month, fallback_latest
        )
        u = self._open_component(ufiles, "u10")
        v = self._open_component(vfiles, "v10")
        u, v = xr.align(u, v, join="inner")
        wind = self._southern_ocean((u**2 + v**2) ** 0.5)
        if "time" in wind.dims:
            wind = wind.mean("time", skipna=True)
        wind.name = "wind_speed"
        wind.attrs.update(
            {
                "long_name": "10 m wind speed",
                "units": u.attrs.get("units", "m s-1"),
                "source": "ERA5" if family == "era5" else "ERA5T",
                "requested_year": requested_year,
                "requested_month": requested_month,
                "selected_year": int(year),
                "selected_month": int(month),
                "exact_requested_month": bool(exact),
            }
        )
        return wind
