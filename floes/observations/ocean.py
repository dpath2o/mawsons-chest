from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
import glob
import xarray as xr

from floes.config import FloesConfig

Source = Literal["ACCESS-OM2", "ACCESS-OM3", "EN4", "ORAS5", "IAP"]


@dataclass(frozen=True)
class OceanReader:
    """Small reader for ORAS/EN4/ACCESS-style ocean products.

    This is the `floes` analogue of the earlier `IceReader`, tuned for observational
    and reanalysis products used in the monthly discussion figures.
    """

    config: FloesConfig

    def read(
        self,
        *,
        src: Source,
        var: str,
        start_year: int,
        end_year: int,
        expt: str = "obs",
        freq: str = "1mon",
        latmin: float = -90.0,
        latmax: float = 90.0,
        zmin: float = 0.0,
        zmax: float = 6000.0,
        chunks="auto",
        parallel: bool = False,
    ) -> xr.DataArray:
        years = [str(y) for y in range(start_year, end_year + 1)]
        files = self._get_filepaths(src=src, expt=expt, var=var, years=years, freq=freq)
        if not files:
            raise FileNotFoundError(f"No files found for src={src}, var={var}, years={start_year}-{end_year}")

        if src == "ORAS5":
            ysl = self._oras5_yslice(files[0], latmin, latmax)

            def preprocess(ds: xr.Dataset) -> xr.Dataset:
                da = ds[var].isel(x=slice(0, 1440), y=ysl)
                if "deptht" in da.dims:
                    da = da.sel(deptht=slice(zmin, zmax))
                return da.to_dataset(name=var)

            ds = xr.open_mfdataset(files, preprocess=preprocess, chunks=chunks, parallel=parallel, decode_timedelta=False)
            return ds[var]

        dims = self._infer_var_dims(files[0], var=var)
        preprocess = self._preprocess_generic(var=var, dims=dims, latmin=latmin, latmax=latmax, zmin=zmin, zmax=zmax)
        ds = xr.open_mfdataset(files, preprocess=preprocess, chunks=chunks, parallel=parallel, decode_timedelta=False)
        if var not in ds:
            raise KeyError(f"Variable {var!r} not found after opening files.")
        return ds[var]

    def _get_filepaths(self, *, src: Source, expt: str, var: str, years: list[str], freq: str) -> list[str]:
        if src in {"ACCESS-OM2", "ACCESS-OM3"}:
            try:
                import intake  # noqa: F401
            except ImportError as exc:
                raise ImportError("ACCESS model reading requires intake and the access-nri catalog.") from exc
            catalog = intake.cat.access_nri.search(model=src, variable=var, frequency=freq)
            pattern = catalog[expt].search(variable=var).df["path"].tolist()
            return [pattern[0]] if freq == "fx" else sorted([p for p in pattern if any(y in p for y in years)])

        base = Path(self.config.gadi_base) / src
        if src == "EN4":
            pattern = str(base / "EN.4.2.2.?.analysis.l09.*.nc")
        elif src == "ORAS5":
            pattern = str(base / var / f"ORAS5_{var}_monthly_SOcean_*.nc")
        elif src == "IAP":
            pattern = str(base / var / f"IAP*_{var.capitalize()}_monthly_*.nc")
        else:
            pattern = str(base / var / f"{src}*_{var}_monthly_*.nc")
        return sorted([f for f in glob.glob(pattern) if any(y in f for y in years)])

    def _infer_var_dims(self, path: str, *, var: str) -> tuple[str, ...]:
        with xr.open_dataset(path, decode_timedelta=False) as ds:
            if var not in ds:
                raise KeyError(f"Variable {var!r} not found in {path}")
            return ds[var].dims

    def _preprocess_generic(self, *, var: str, dims: tuple[str, ...], latmin: float, latmax: float, zmin: float, zmax: float) -> Callable[[xr.Dataset], xr.Dataset]:
        if len(dims) == 4:
            zdim, latdim = dims[1], dims[2]
            space_range = {zdim: slice(zmin, zmax), latdim: slice(latmin, latmax)}
        elif len(dims) == 3:
            latdim = dims[1]
            space_range = {latdim: slice(latmin, latmax)}
        else:
            space_range = {}

        def _sel(ds: xr.Dataset) -> xr.Dataset:
            if space_range:
                ds = ds.sel(**space_range)
            return ds

        return _sel

    def _oras5_yslice(self, sample_path: str, latmin: float, latmax: float) -> slice:
        import numpy as np
        with xr.open_dataset(sample_path, decode_timedelta=False) as ds0:
            lat1d = ds0["nav_lat"].isel(x=0).values
        jj = np.where((lat1d >= latmin) & (lat1d <= latmax))[0]
        if jj.size == 0:
            raise ValueError(f"No ORAS5 y indices found for lat range [{latmin}, {latmax}]")
        return slice(int(jj.min()), int(jj.max()) + 1)
