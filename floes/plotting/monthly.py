from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import xarray as xr

from floes.config import FloesConfig

from .palettes import make_cpt, make_symmetric_cpt
from .pygmt_base import (
    has_curvilinear_lon_lat,
    plot_geographic_contour,
    require_pygmt,
    south_polar_projection,
    south_polar_region,
    write_xyz_from_curvilinear,
)


def _selected_ym_from_attrs(
    obj: xr.Dataset | xr.DataArray, fallback_year: int | None = None, fallback_month: int | None = None
) -> tuple[int | None, int | None]:
    attrs = obj.attrs
    y = attrs.get("selected_year", fallback_year)
    m = attrs.get("selected_month", fallback_month)
    return (int(y) if y is not None else None, int(m) if m is not None else None)


@dataclass
class MonthlySeaIceChatPlotter:
    """PyGMT-first plotting helpers for the monthly sea-ice science-chat figures."""

    config: FloesConfig

    def _figure(self):
        pygmt = require_pygmt()
        return pygmt, pygmt.Figure()

    def _plot_field(
        self,
        fig,
        da: xr.DataArray,
        *,
        cpt_path: Path,
        title: str,
        region: list[float],
        projection: str,
        output: Path,
        stride: int,
    ) -> None:
        """Plot regular grids as rasters and curvilinear grids as lon/lat cells."""
        field = da.squeeze()
        if has_curvilinear_lon_lat(field):
            xyz = output.with_suffix(f".{field.name or 'field'}.xyz")
            write_xyz_from_curvilinear(field, xyz, stride=stride)
            fig.basemap(region=region, projection=projection, frame=["afg", f"+t{title}"])
            fig.plot(
                data=str(xyz),
                style=f"s{0.04 * stride:.3f}c",
                cmap=str(cpt_path),
                fill="+z",
                pen=None,
            )
        else:
            fig.grdimage(
                field,
                region=region,
                projection=projection,
                cmap=str(cpt_path),
                frame=["afg", f"+t{title}"],
            )
        fig.coast(shorelines="0.25p,black", land="gray80")

    def plot_sic_anomaly_map(
        self, ds: xr.Dataset, *, year: int, month: int, output: Path, title: str | None = None, stride: int = 1
    ) -> Path:
        """Plot SIC anomaly with climatological and current 15 percent ice-edge contours."""
        pygmt, fig = self._figure()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        region = south_polar_region(self.config.latmax_sh)
        projection = south_polar_projection("16c")
        sy, sm = _selected_ym_from_attrs(ds, year, month)
        title = title or f"{sy:04d}-{sm:02d}"
        anom = ds["sic_anom"].squeeze()
        cpt_path = output.with_suffix(".sic_anom.cpt")
        make_symmetric_cpt(pygmt, cmap="polar", limit=1.0, output=cpt_path, series_step=0.1)
        self._plot_field(
            fig,
            anom,
            cpt_path=cpt_path,
            title=title,
            region=region,
            projection=projection,
            output=output,
            stride=stride,
        )
        for name, pen in (("sic_clim", "1.0p,violetred3"), ("sic", "1.0p,black")):
            if name not in ds:
                continue
            plot_geographic_contour(fig, ds[name], level=self.config.sic_threshold, pen=pen)
        fig.colorbar(frame=["x+lSIC anomaly", "y+lfraction"])
        fig.savefig(str(output), dpi=200)
        return output

    def plot_total_sia_sie(
        self, ds: xr.Dataset, *, output: Path, title: str = "Southern Hemisphere total sea ice"
    ) -> Path:
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
        cols = [c for c in ("SIA", "SIE") if c in df]
        ymin = float(df[cols].min().min())
        ymax = float(df[cols].max().max())
        xmin = float(df["year"].min())
        xmax = float(df["year"].max())
        pad = max((ymax - ymin) * 0.08, 0.25)
        region = [xmin, xmax, max(0, ymin - pad), ymax + pad]
        # Do not pass explicit frame-side codes here. GMT builds packaged with
        # different analysis3 releases disagree on whether mixed-case strings
        # such as WSen/WSne are valid. The default frame axes are portable.
        fig.basemap(
            region=region,
            projection="X18c/9c",
            frame=["xaf+lYear", "yaf+l10@+6@+ km@+2@+", f"+t{title}"],
        )
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
        value_range: tuple[float, float] | None = None,
        colorbar_label: str | None = None,
        colorbar_unit: str | None = None,
        ice_edge: xr.DataArray | None = None,
        contour: xr.DataArray | None = None,
        contour_interval: float | None = None,
        contour_annotation: float | str | None = None,
        contour_pen: str = "0.45p,gray40",
        projection_width: str = "16c",
        stride: int = 1,
    ) -> Path:
        """Generic PyGMT gridded anomaly/field map."""
        pygmt, fig = self._figure()
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        region = south_polar_region(self.config.latmax_sh)
        projection = south_polar_projection(projection_width)
        cpt_path = output.with_suffix(".cpt")
        if value_range is None:
            make_symmetric_cpt(pygmt, cmap=cpt, limit=limit, output=cpt_path)
        else:
            make_cpt(pygmt, cmap=cpt, minimum=value_range[0], maximum=value_range[1], output=cpt_path)
        self._plot_field(
            fig,
            da,
            cpt_path=cpt_path,
            title=title,
            region=region,
            projection=projection,
            output=output,
            stride=stride,
        )
        if contour is not None:
            fig.grdcontour(
                grid=contour.squeeze(),
                levels=contour_interval,
                annotation=contour_annotation,
                pen=contour_pen,
            )
        if ice_edge is not None:
            plot_geographic_contour(fig, ice_edge, level=self.config.sic_threshold, pen="1.0p,black")
        x_label = colorbar_label or units_label
        frame = [f"x+l{x_label}"]
        if colorbar_unit:
            frame.append(f"y+l{colorbar_unit}")
        fig.colorbar(frame=frame)
        fig.savefig(str(output), dpi=200)
        return output
