from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from floes.observations.sea_ice import (
    annual_mean_complete,
    monthly_anomalies,
    standardised_monthly_anomalies,
    year_month_matrix,
)


def _pyplot():
    """Import matplotlib lazily so map-only workflows remain PyGMT-only."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _save(fig, output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, bbox_inches="tight", facecolor="white")
    _pyplot().close(fig)
    return output


def _decimal_year(time: xr.DataArray) -> np.ndarray:
    index = pd.DatetimeIndex(time.values)
    return index.year + (index.dayofyear - 1) / np.where(index.is_leap_year, 366.0, 365.0)


@dataclass
class NSIDCDiagnosticPlotter:
    """Matplotlib reproductions of the legacy NSIDC NCL/notebook figures."""

    climatology_start: int = 1979
    climatology_end: int = 2018
    comparison_split_year: int = 2005

    def plot_monthly_anomaly_timeseries(
        self,
        da: xr.DataArray,
        *,
        output: Path,
        standardised: bool = False,
        hemisphere_name: str = "Southern Hemisphere",
        highlight_year: int | None = None,
    ) -> Path:
        if standardised:
            values = standardised_monthly_anomalies(
                da, start_year=self.climatology_start, end_year=self.climatology_end
            )
            ylabel = r"Standardised sea-ice area anomaly ($\sigma$)"
        else:
            values = monthly_anomalies(da, start_year=self.climatology_start, end_year=self.climatology_end)
            ylabel = r"Sea-ice area anomaly (million km$^2$)"

        x = _decimal_year(values["time"])
        y = np.asarray(values.values, dtype=float)
        years = pd.DatetimeIndex(values["time"].values).year
        highlighted = years == highlight_year if highlight_year is not None else np.zeros_like(y, dtype=bool)
        background = ~highlighted
        plt = _pyplot()
        fig, ax = plt.subplots(figsize=(10, 5.7))
        ax.fill_between(x, 0, y, where=(y >= 0) & background, color="cyan", interpolate=True)
        ax.fill_between(x, 0, y, where=(y < 0) & background, color="orange", interpolate=True)
        ax.fill_between(x, 0, y, where=(y >= 0) & highlighted, color="purple", interpolate=True)
        ax.fill_between(x, 0, y, where=(y < 0) & highlighted, color="yellow", interpolate=True)
        ax.plot(x, y, color="black", linewidth=1.0)
        ax.axhline(0, color="0.35", linewidth=0.7)
        if standardised:
            ax.axhline(1.96, color="0.25", linewidth=0.7, linestyle="--")
            ax.axhline(-1.96, color="0.25", linewidth=0.7, linestyle="--")
        ax.set_xlabel("Year")
        ax.set_ylabel(ylabel)
        ax.set_title(
            f"{hemisphere_name} monthly sea-ice area anomalies ({self.climatology_start}–{self.climatology_end})"
        )
        ax.grid(axis="y", color="0.9", linewidth=0.5)
        ax.margins(x=0)
        if highlighted.any():
            from matplotlib.patches import Patch

            ax.legend(
                handles=[
                    Patch(facecolor="purple", label=f"{highlight_year} positive"),
                    Patch(facecolor="yellow", edgecolor="0.4", label=f"{highlight_year} negative"),
                ],
                loc="upper left",
                frameon=False,
                fontsize=8,
            )
        return _save(fig, output)

    def plot_hemisphere_comparison(
        self,
        sh: xr.Dataset,
        nh: xr.Dataset,
        *,
        annual_output: Path,
        monthly_output: Path,
    ) -> tuple[Path, Path]:
        if "SIE" not in sh or "SIE" not in nh:
            raise KeyError("Both hemispheres must contain SIE.")
        sh_sie, nh_sie = xr.align(sh["SIE"], nh["SIE"], join="inner")
        global_sie = sh_sie + nh_sie
        sh_ann = annual_mean_complete(sh_sie)
        nh_ann = annual_mean_complete(nh_sie)
        global_ann = annual_mean_complete(global_sie)
        sh_ann, nh_ann, global_ann = xr.align(sh_ann, nh_ann, global_ann, join="inner")

        plt = _pyplot()
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
        ax = axes[0]
        ax.plot(global_ann["year"], global_ann, color="black", linewidth=1.3)
        ax.axvline(self.comparison_split_year, color="red", linewidth=0.8, alpha=0.7)
        ax.set_title("Global total SIE", loc="left")
        ax.set_xlabel("Year")
        ax.set_ylabel(r"Global SIE (million km$^2$)")

        ax = axes[1]
        before = sh_ann["year"] < self.comparison_split_year
        after = ~before
        ax.scatter(
            sh_ann.where(before), nh_ann.where(before), s=20, color="black", label=f"<{self.comparison_split_year}"
        )
        ax.scatter(sh_ann.where(after), nh_ann.where(after), s=20, color="red", label=f"≥{self.comparison_split_year}")
        if bool(before.any()):
            ax.axvline(float(sh_ann.where(before).mean()), color="0.5", linewidth=0.7)
            ax.axhline(float(nh_ann.where(before).mean()), color="0.5", linewidth=0.7)
        if bool(after.any()):
            ax.axvline(float(sh_ann.where(after).mean()), color="red", linewidth=0.7, alpha=0.6)
            ax.axhline(float(nh_ann.where(after).mean()), color="red", linewidth=0.7, alpha=0.6)
        ax.set_title("Arctic vs Antarctic", loc="left")
        ax.set_xlabel(r"Antarctic SIE (million km$^2$)")
        ax.set_ylabel(r"Arctic SIE (million km$^2$)")
        ax.legend(frameon=False, fontsize=8)
        fig.suptitle("Annual")
        annual_path = _save(fig, annual_output)

        sh_anom = monthly_anomalies(sh_sie, start_year=self.climatology_start, end_year=self.climatology_end)
        nh_anom = monthly_anomalies(nh_sie, start_year=self.climatology_start, end_year=self.climatology_end)
        sh_anom, nh_anom = xr.align(sh_anom, nh_anom, join="inner")
        global_anom = sh_anom + nh_anom
        x = _decimal_year(global_anom["time"])
        recent = global_anom["time"].dt.year >= self.comparison_split_year

        fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
        ax = axes[0]
        ax.plot(x, global_anom, color="black", linewidth=1.0)
        ax.axhline(0, color="0.4", linewidth=0.7)
        ax.set_title("Global total SIE", loc="left")
        ax.set_xlabel("Year")
        ax.set_ylabel(r"Global SIE anomaly (million km$^2$)")
        ax.margins(x=0)

        ax = axes[1]
        ax.scatter(sh_anom.where(~recent), nh_anom.where(~recent), s=12, color="black")
        ax.scatter(sh_anom.where(recent), nh_anom.where(recent), s=12, color="red")
        ax.axvline(0, color="0.4", linewidth=0.7)
        ax.axhline(0, color="0.4", linewidth=0.7)
        ax.set_title("Arctic vs Antarctic", loc="left")
        ax.set_xlabel(r"Antarctic SIE anomaly (million km$^2$)")
        ax.set_ylabel(r"Arctic SIE anomaly (million km$^2$)")
        fig.suptitle(f"Monthly anomalies ({self.climatology_start}–{self.climatology_end} climatology)")
        monthly_path = _save(fig, monthly_output)
        return annual_path, monthly_path

    def plot_monthly_anomalies_by_year(
        self,
        da: xr.DataArray,
        *,
        output: Path,
        highlight_year: int,
    ) -> Path:
        anomaly = monthly_anomalies(da, start_year=self.climatology_start, end_year=self.climatology_end)
        matrix = year_month_matrix(anomaly)
        plt = _pyplot()
        fig, ax = plt.subplots(figsize=(10, 5.7))
        for year in matrix["year"].values:
            if int(year) == highlight_year:
                continue
            ax.plot(matrix["month"], matrix.sel(year=year), color="0.4", linewidth=0.65, alpha=0.8)
        if highlight_year in matrix["year"]:
            ax.plot(
                matrix["month"],
                matrix.sel(year=highlight_year),
                color="orange",
                linewidth=2.8,
                label=str(highlight_year),
            )
            ax.legend(loc="upper right", frameon=True)
        ax.axhline(0, color="0.4", linewidth=0.7)
        ax.set_xlim(1, 12)
        ax.set_xticks(
            np.arange(1, 13), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        )
        ax.set_ylabel(r"Sea-ice extent anomaly (million km$^2$)")
        ax.set_title(f"Southern Hemisphere monthly SIE anomalies ({self.climatology_start}–{self.climatology_end})")
        return _save(fig, output)

    def plot_sie_maximum_vs_day(
        self,
        maxima: xr.Dataset,
        *,
        output: Path,
        current_year: int | None = None,
        comparison_year: int = 2014,
    ) -> Path:
        plt = _pyplot()
        fig, ax = plt.subplots(figsize=(6, 5.5))
        ax.scatter(maxima["day_of_max"], maxima["SIE_max"], color="black", s=34)
        available = {int(y) for y in maxima["year"].values}
        latest_year = current_year if current_year in available else (max(available) if available else None)
        previous_year = latest_year - 1 if latest_year is not None and latest_year - 1 in available else None
        if previous_year is not None:
            sel = maxima.sel(year=previous_year)
            ax.scatter(sel["day_of_max"], sel["SIE_max"], color="red", s=42, label=str(previous_year))
        if comparison_year in available:
            sel = maxima.sel(year=comparison_year)
            ax.scatter(
                sel["day_of_max"],
                sel["SIE_max"],
                color="royalblue",
                edgecolor="0.3",
                linewidth=0.4,
                s=44,
                label=str(comparison_year),
            )
        if latest_year is not None:
            sel = maxima.sel(year=latest_year)
            ax.scatter(
                sel["day_of_max"],
                sel["SIE_max"],
                color="yellow",
                edgecolor="0.3",
                linewidth=0.5,
                s=52,
                label=str(latest_year),
                zorder=4,
            )
        ax.set_xlabel("Day of maximum SIE")
        ax.set_ylabel(r"Maximum SIE (million km$^2$)")
        title = "Southern Hemisphere annual maximum SIE"
        data_end = maxima.attrs.get("data_end")
        if data_end:
            end = pd.Timestamp(data_end)
            if end.year not in available:
                title += f"\nData through {end:%d %b %Y}; latest complete maximum {latest_year}"
            elif end < pd.Timestamp(year=end.year, month=10, day=31):
                title += f"\n{end.year} is provisional to {end:%d %b}"
        ax.set_title(title)
        if previous_year is not None or comparison_year in available or latest_year is not None:
            ax.legend(frameon=False, fontsize=8)
        return _save(fig, output)
