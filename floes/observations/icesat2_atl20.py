from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import h5py
import numpy as np
import pandas as pd
import xarray as xr

from floes.config import FloesConfig

_RX = re.compile(r"ATL20-(?P<hemi>01|02)_(?P<date>\d{8})\d{6}_[^_]+_005_(?P<rev>\d{2})\.h5$")


@dataclass
class ICESat2ATL20Reader:
    """Read ICESat-2 ATL20 v005 monthly gridded sea-ice freeboard."""

    config: FloesConfig
    hemisphere: str = "SH"
    version: str = "V005"

    def __post_init__(self) -> None:
        self.hemisphere = self.hemisphere.upper()
        if self.hemisphere not in {"SH", "NH"}:
            raise ValueError("hemisphere must be SH or NH")

    @property
    def root(self) -> Path:
        return Path(self.config.seaice_root) / "ICESat2" / "ATL20" / self.version / self.hemisphere

    def available_files(self) -> list[Path]:
        return sorted(self.root.glob("*/*/ATL20-*.h5"))

    @staticmethod
    def _stamp(path: Path) -> pd.Timestamp:
        m = _RX.match(path.name)
        if not m:
            raise ValueError(f"Unrecognised ATL20 filename: {path.name}")
        return pd.Timestamp(m.group("date"))

    @staticmethod
    def _read_dataset(group: h5py.Group, candidates: tuple[str, ...]) -> np.ndarray:
        for name in candidates:
            if name in group:
                return np.asarray(group[name])
        raise KeyError(f"None of {candidates} found in {group.name}; available={list(group.keys())}")

    def month(self, *, year: int, month: int, fallback_latest: bool = True) -> xr.DataArray:
        files = self.available_files()
        if not files:
            raise FileNotFoundError(f"No ATL20 v005 files found under {self.root}")

        grouped: dict[tuple[int, int], list[Path]] = {}
        for path in files:
            stamp = self._stamp(path)
            grouped.setdefault((stamp.year, stamp.month), []).append(path)

        requested = (int(year), int(month))
        if requested in grouped:
            selected, exact = requested, True
        else:
            if not fallback_latest:
                raise ValueError(f"ATL20 unavailable for {year:04d}-{month:02d}")
            candidates = [ym for ym in grouped if ym <= requested]
            selected = max(candidates or grouped)
            exact = False

        path = sorted(grouped[selected])[-1]
        with h5py.File(path, "r") as h:
            monthly = h["monthly"]
            fb_name = next(
                (n for n in ("mean_fb", "mean_freeboard", "freeboard", "monthly_mean_fb") if n in monthly),
                None,
            )
            if fb_name is None:
                raise KeyError(f"No recognised monthly freeboard variable; available={list(monthly.keys())}")
            mean_fb = np.asarray(monthly[fb_name], dtype="float32")
            lon = self._read_dataset(h, ("grid_lon",)).astype("float32")
            lat = self._read_dataset(h, ("grid_lat",)).astype("float32")
            x = self._read_dataset(h, ("grid_x",)).astype("float32")
            y = self._read_dataset(h, ("grid_y",)).astype("float32")
            fill = monthly[fb_name].attrs.get("_FillValue")
            if fill is not None:
                mean_fb = np.where(mean_fb == fill, np.nan, mean_fb)

        target = (len(y), len(x))
        if mean_fb.shape != target and mean_fb.T.shape == target:
            mean_fb = mean_fb.T
        if lon.shape != target and lon.T.shape == target:
            lon = lon.T
        if lat.shape != target and lat.T.shape == target:
            lat = lat.T

        da = xr.DataArray(
            mean_fb,
            dims=("y", "x"),
            coords={
                "x": ("x", x),
                "y": ("y", y),
                "longitude": (("y", "x"), lon),
                "latitude": (("y", "x"), lat),
            },
            name="freeboard",
            attrs={
                "long_name": "ICESat-2 ATL20 monthly mean sea-ice freeboard",
                "units": "m",
                "source": "NASA NSIDC ATL20 v005",
                "requested_year": requested[0],
                "requested_month": requested[1],
                "selected_year": selected[0],
                "selected_month": selected[1],
                "exact_requested_month": exact,
                "source_file": str(path),
            },
        )
        return da.where(np.isfinite(da))

    def monthly_mean_series(self) -> xr.DataArray:
        """Area-unweighted mean of valid ATL20 monthly grid cells."""
        files = self.available_files()
        grouped: dict[tuple[int, int], list[Path]] = {}
        for path in files:
            stamp = self._stamp(path)
            grouped.setdefault((stamp.year, stamp.month), []).append(path)

        times, values = [], []
        for year, month in sorted(grouped):
            da = self.month(year=year, month=month, fallback_latest=False)
            times.append(pd.Timestamp(year, month, 1))
            values.append(float(da.mean(skipna=True)))

        return xr.DataArray(
            values,
            dims=("time",),
            coords={"time": times},
            name="freeboard",
            attrs={
                "long_name": "Southern Hemisphere spatial-mean ATL20 monthly sea-ice freeboard",
                "units": "m",
                "source": "NASA NSIDC ATL20 v005",
            },
        )
