from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import xarray as xr

from floes.config import FloesConfig

from .gridded import attach_lon_lat_from_cf_projection


_MONTH_RE = re.compile(r"-(\d{6})-fv", re.IGNORECASE)


@dataclass
class ESACCISITReader:
    """Read monthly gridded ESA CCI L3C Southern Hemisphere thickness."""

    config: FloesConfig
    version: str = "v4.0"
    hemisphere: str = "SH"

    @property
    def root(self) -> Path:
        return Path(self.config.seaice_root) / "ESA" / "CCI" / "thickness" / "L3C"

    def available_files(self) -> list[Path]:
        return sorted(self.root.glob(f"*/{self.version}/{self.hemisphere}/*/*.nc"))

    @staticmethod
    def _year_month(path: Path) -> tuple[int, int] | None:
        match = _MONTH_RE.search(path.name)
        if not match:
            return None
        stamp = match.group(1)
        return int(stamp[:4]), int(stamp[4:6])

    def month(self, *, year: int, month: int, fallback_latest: bool = True) -> xr.DataArray:
        grouped: dict[tuple[int, int], list[Path]] = {}
        for path in self.available_files():
            ym = self._year_month(path)
            if ym:
                grouped.setdefault(ym, []).append(path)
        if not grouped:
            raise FileNotFoundError(f"No ESA CCI L3C SIT files found under {self.root}")

        requested = (int(year), int(month))
        if requested in grouped:
            selected = requested
            exact = True
        else:
            if not fallback_latest:
                raise ValueError(f"ESA CCI L3C SIT is unavailable for {year:04d}-{month:02d}")
            candidates = [ym for ym in grouped if ym <= requested]
            selected = max(candidates or grouped)
            exact = False

        fields: list[xr.DataArray] = []
        sensors: list[str] = []
        for path in grouped[selected]:
            ds = xr.open_dataset(path, chunks=self.config.chunks, decode_timedelta=False)
            name = next(
                (
                    candidate
                    for candidate in ("sea_ice_thickness", "sea_ice_thickness_mean", "sit")
                    if candidate in ds
                ),
                None,
            )
            if name is None:
                continue
            field = attach_lon_lat_from_cf_projection(ds[name].squeeze(drop=True), ds).astype("float32")
            field = field.where(field >= 0)
            fields.append(field)
            sensors.append(path.parts[-5])
        if not fields:
            raise KeyError(f"No recognised SIT field for ESA CCI month {selected[0]:04d}-{selected[1]:02d}")

        if len(fields) == 1:
            out = fields[0]
        else:
            aligned = xr.align(*fields, join="inner")
            out = xr.concat(aligned, dim="sensor").mean("sensor", skipna=True)
        out.name = "sit"
        out.attrs.update(
            {
                "long_name": "sea ice thickness",
                "units": "m",
                "source": "ESA CCI L3C " + "+".join(sorted(set(sensors))),
                "requested_year": requested[0],
                "requested_month": requested[1],
                "selected_year": selected[0],
                "selected_month": selected[1],
                "exact_requested_month": exact,
            }
        )
        return out
