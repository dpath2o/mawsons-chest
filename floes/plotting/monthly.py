from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd
import xarray as xr

from floes.config import FloesConfig
from .pygmt_base import require_pygmt, south_polar_projection, south_polar_region, write_xyz_from_curvilinear
from .palettes import make_symmetric_cpt


@dataclass
class MonthlySeaIceChatPlotter:
    """PyGMT-first plotting helpers for the monthly sea-ice science-chat figures."""

    config: FloesConfig

    def _figure(self):
        pygmt = require_pygmt()
        return pygmt, pygmt.Figure()

    def plot_sic_anomaly_map(
        self,
        ds: xr.Dataset,
        *,
        year: int,
        month: int,
        output: Path,
        title: str | None = None,
        stride: int = 1,
    ) -> Path:
        """Plot SIC anomaly with climatological and current 15 percent ice-edge contours."""
        pygmt, fig = self._figure()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        region = south_polar_region(self.config.latmax_sh)
        projection = south_polar_projection("16c")
        title = title or f"NSIDC SIC anomaly, {year:04d}-{month:02d}"

        anom = ds["sic_anom"].squeeze()
        cpt_path = output.with_suffix(".sic_anom.cpt")
        make_symmetric_cpt(pygmt, cmap="polar", limit=1.0, output=cpt_path, series_step=0.1)

        try:
            # Works for regular lon/lat grids and some projected grids with georeference metadata.
            fig.grdimage(anom, region=region, projection=projection, cmap=str(cpt_path), frame=["afg", f"+t{title}"])
        except Exception:
            # Curvilinear/2-D lon-lat fallback. Slower but robust for NSIDC-style products.
            xyz = output.with_suffix(".xyz")
            write_xyz_from_curvilinear(anom, xyz, stride=stride)
            fig.coast(region=region, projection=projection, land="gray80", water="white", shorelines="0.25p,black", frame=["afg", f"+t{title}"])
            fig.plot(data=str(xyz), style="s0.035c", cmap=str(cpt_path), fill="+z", pen=None)

        for name, pen in (("sic_clim", "1.0p,violetred3"), ("sic", "1.0p,black")):
            if name not in ds:
                continue
            try:
                fig.grdcontour(ds[name].squeeze(), levels=[self.config.sic_threshold], pen=pen)
            except Exception:
                pass

        fig.colorbar(frame=['x+l"SIC anomaly"', 'y+l"fraction"'])
        fig.savefig(str(output), dpi=200)
        return output

    def plot_total_sia_sie(self, ds: xr.Dataset, *, output: Path, title: str = "Southern Hemisphere total sea ice") -> Path:
        """Plot SIA/SIE time series using PyGMT."""
        pygmt, fig = self._figure()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        if "time" not in ds.coords:
            raise ValueError("Dataset must contain a time coordinate for SIA/SIE plotting.")
        df = ds[[v for v in ("SIA", "SIE") if v in ds]].to_dataframe().reset_index()
        if df.empty:
            raise ValueError("No SIA/SIE values available for plotting.")
        df["year"] = pd.to_datetime(df["time"]).dt.year + (pd.to_datetime(df["time"]).dt.month - 0.5) / 12.0
        ymin = float(df[[c for c in ("SIA", "SIE") if c in df]].min().min())
        ymax = float(df[[c for c in ("SIA", "SIE") if c in df]].max().max())
        xmin = float(df["year"].min())
        xmax = float(df["year"].max())
        pad = max((ymax - ymin) * 0.08, 0.25)
        region = [xmin, xmax, max(0, ymin - pad), ymax + pad]
        fig.basemap(region=region, projection="X18c/9c", frame=["WSen", "xaf+lYear", "yaf+l10@+6@+ km@+2@+", f"+t{title}"])
        if "SIA" in df:
            fig.plot(x=df["year"], y=df["SIA"], pen="1.2p,black", label="SIA")
        if "SIE" in df:
            fig.plot(x=df["year"], y=df["SIE"], pen="1.2p,gray40,-", label="SIE")
        fig.legend(position="JTR+jTR+o0.2c", box="+gwhite+p0.25p")
        fig.savefig(str(output), dpi=200)
        return output

    def plot_gridded_anomaly(
        self,
        da: xr.DataArray,
        *,
        output: Path,
        title: str,
        cpt: str = "polar",
        limit: float = 3.0,
        units_label: str = "anomaly",
        projection_width: str = "16c",
        stride: int = 1,
    ) -> Path:
        """Generic PyGMT gridded anomaly map."""
        pygmt, fig = self._figure()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        region = south_polar_region(self.config.latmax_sh)
        projection = south_polar_projection(projection_width)
        cpt_path = output.with_suffix(".cpt")
        make_symmetric_cpt(pygmt, cmap=cpt, limit=limit, output=cpt_path)
        try:
            fig.grdimage(da.squeeze(), region=region, projection=projection, cmap=str(cpt_path), frame=["afg", f"+t{title}"])
            fig.coast(shorelines="0.25p,black", land="gray80")
        except Exception:
            xyz = output.with_suffix(".xyz")
            write_xyz_from_curvilinear(da.squeeze(), xyz, stride=stride)
            fig.coast(region=region, projection=projection, land="gray80", water="white", shorelines="0.25p,black", frame=["afg", f"+t{title}"])
            fig.plot(data=str(xyz), style="s0.035c", cmap=str(cpt_path), fill="+z", pen=None)
        fig.colorbar(frame=[f'x+l"{units_label}"'])
        fig.savefig(str(output), dpi=200)
        return output
