from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import logging
import tempfile

import imageio.v2 as imageio
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pygmt
import xarray as xr
from pyproj import CRS, Geod, Transformer


@dataclass
class FigurePaths:
    cice_history: Path
    nsidc_daily_south: Path
    nsidc_daily_north: Path
    nsidc_cell_area_south: Path
    nsidc_cell_area_north: Path
    output_dir: Path
    animation_dir: Path


class Mawsons_Tools:
    """
    Lightweight figure/diagnostic toolbox for direct CICE history files and
    daily NSIDC sea-ice concentration files.

    The class is intentionally config-free: paths, thresholds, plotting defaults,
    and variable names are initialised directly in ``__init__``.
    """

    def __init__(
        self,
        *,
        cice_history_dir: str | Path = "/g/data/gv90/da1339/cice-dirs/runs/free-slip-waves/history",
        nsidc_daily_south_dir: str | Path = "/g/data/gv90/da1339/SeaIce/NSIDC/G02202_V4/south/daily",
        nsidc_daily_north_dir: str | Path = "/g/data/gv90/da1339/SeaIce/NSIDC/G02202_V4/north/daily",
        nsidc_cell_area_south: str | Path = "/g/data/gv90/da1339/SeaIce/NSIDC/NSIDC0771/NSIDC0771_CellArea_PS_S25km_v1.1.nc",
        nsidc_cell_area_north: str | Path = "/g/data/gv90/da1339/SeaIce/NSIDC/NSIDC0771/NSIDC0771_CellArea_PS_N25km_v1.1.nc",
        output_dir: str | Path = "./figures",
        animation_dir: str | Path = "./animations",
        cice_time_offset_days: int = 1,
        sic_threshold: float = 0.15,
        cice_aice_name: str = "aice",
        cice_hi_name: str = "hi",
        cice_area_name: str = "tarea",
        cice_lat_name: str = "TLAT",
        nsidc_sic_preference: str = "cdr_seaice_conc",
        lon_wrap: str = "0-360",
        south_region: tuple[float, float, float, float] = (0, 360, -90, -50),
        north_region: tuple[float, float, float, float] = (0, 360, 50, 90),
        south_projection: str = "S0/-90/20c",
        north_projection: str = "S0/90/20c",
        point_style: str = "c0.08c",
        nsidc_pen: str = "0.8p,green@35",
        cmap_aice: str = "cmocean/ice",
        cmap_hi: str = "cmocean/amp",
        hi_range: tuple[float, float] = (0.0, 5.0),
        pygmt_font_title: str = "20p,Bookman-Demi",
        pygmt_font_annot_primary: str = "18p,NewCenturySchlbk-Roman",
        pygmt_font_annot_secondary: str = "18p,NewCenturySchlbk-Bold",
        pygmt_font_label: str = "18p,NewCenturySchlbk-Bold",
        log_level: int = logging.INFO,
    ):
        self.paths = FigurePaths(
            cice_history=Path(cice_history_dir),
            nsidc_daily_south=Path(nsidc_daily_south_dir),
            nsidc_daily_north=Path(nsidc_daily_north_dir),
            nsidc_cell_area_south=Path(nsidc_cell_area_south),
            nsidc_cell_area_north=Path(nsidc_cell_area_north),
            output_dir=Path(output_dir),
            animation_dir=Path(animation_dir),
        )
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.paths.animation_dir.mkdir(parents=True, exist_ok=True)

        self.cice_time_offset_days = int(cice_time_offset_days)
        self.sic_threshold = float(sic_threshold)
        self.cice_aice_name = cice_aice_name
        self.cice_hi_name = cice_hi_name
        self.cice_area_name = cice_area_name
        self.cice_lat_name = cice_lat_name
        self.nsidc_sic_preference = nsidc_sic_preference
        self.lon_wrap = lon_wrap
        self.south_region = south_region
        self.north_region = north_region
        self.south_projection = south_projection
        self.north_projection = north_projection
        self.point_style = point_style
        self.nsidc_pen = nsidc_pen
        self.cmap_aice = cmap_aice
        self.cmap_hi = cmap_hi
        self.hi_range = hi_range
        self.pygmt_config = {
            "FONT_TITLE": pygmt_font_title,
            "FONT_ANNOT_PRIMARY": pygmt_font_annot_primary,
            "FONT_ANNOT_SECONDARY": pygmt_font_annot_secondary,
            "FONT_LABEL": pygmt_font_label,
            "COLOR_FOREGROUND": "black",
        }

        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self.logger.addHandler(handler)
        self.logger.setLevel(log_level)
        self.logger.propagate = False

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------
    @staticmethod
    def is_dask_array(x) -> bool:
        return hasattr(x, "compute") and ("dask" in type(x).__module__.lower())

    @staticmethod
    def auto_mask_zero(da: xr.DataArray) -> bool:
        name = (da.name or "").lower()
        fv = str(da.attrs.get("flag_values", "")).strip().replace(",", " ")
        is_categorical = ("diff_cat" in name) or (fv in {"0 1 2", "0 1 2 "})
        return not is_categorical

    @staticmethod
    def normalise_longitudes(lon, to: str = "0-360") -> np.ndarray:
        lon = np.asarray(lon, dtype=float)
        if to == "0-360":
            return lon % 360.0
        if to == "-180-180":
            return ((lon + 180.0) % 360.0) - 180.0
        raise ValueError("`to` must be '0-360' or '-180-180'.")

    @staticmethod
    def split_line_by_longitude_jump(lon, lat, *, max_jump: float = 180.0, min_points: int = 2):
        lon = np.asarray(lon, dtype=float)
        lat = np.asarray(lat, dtype=float)
        if lon.size != lat.size:
            raise ValueError("lon and lat must have the same length")
        if lon.size < min_points:
            return []
        jump_idx = np.where(np.abs(np.diff(lon)) > max_jump)[0]
        segments = []
        start = 0
        for idx in jump_idx:
            stop = idx + 1
            if (stop - start) >= min_points:
                segments.append({"lon": lon[start:stop], "lat": lat[start:stop]})
            start = stop
        if (lon.size - start) >= min_points:
            segments.append({"lon": lon[start:], "lat": lat[start:]})
        return segments

    # ------------------------------------------------------------------
    # CICE IO / time helpers
    # ------------------------------------------------------------------
    def get_cice_path(self, date_str: str) -> Path:
        return self.paths.cice_history / f"iceh.{date_str}.nc"

    def load_cice_day(self, date_str: str, *, decode_times: bool = True) -> xr.Dataset:
        path = self.get_cice_path(date_str)
        if not path.exists():
            raise FileNotFoundError(path)
        return xr.open_dataset(path, decode_times=decode_times)

    def cice_corrected_time(self, obj: xr.Dataset | xr.DataArray, *, time_index: int = 0, as_string: bool = False, date_format: str = "%Y-%m-%d"):
        if "time" not in obj.coords:
            raise ValueError("Object does not contain a 'time' coordinate.")
        if obj.coords["time"].size == 0:
            raise ValueError("Object has an empty 'time' coordinate.")
        t = obj.coords["time"].isel(time=time_index).values
        if isinstance(t, np.ndarray):
            t = t.item()
        if isinstance(t, np.datetime64):
            t_corr = t - np.timedelta64(self.cice_time_offset_days, "D")
            return np.datetime_as_string(t_corr, unit="D") if as_string else t_corr
        t_corr = t - timedelta(days=self.cice_time_offset_days)
        return t_corr.strftime(date_format) if as_string else t_corr

    def cice_corrected_datestr(self, obj: xr.Dataset | xr.DataArray, *, time_index: int = 0, date_format: str = "%Y-%m-%d") -> str:
        return self.cice_corrected_time(obj, time_index=time_index, as_string=True, date_format=date_format)

    def cice_corrected_time_coord(self, obj: xr.Dataset | xr.DataArray, *, time_index: int = 0) -> xr.DataArray:
        t_corr = self.cice_corrected_time(obj, time_index=time_index, as_string=False)
        arr = np.array([t_corr], dtype="datetime64[ns]") if isinstance(t_corr, np.datetime64) else np.array([t_corr])
        return xr.DataArray(arr, dims=("time",), coords={"time": arr}, name="time")

    # ------------------------------------------------------------------
    # CICE plotting prep
    # ------------------------------------------------------------------
    @staticmethod
    def resolve_cice_lonlat_2d(
        da2: xr.DataArray,
        *,
        lon_coord_name: str | None = None,
        lat_coord_name: str | None = None,
        infer_if_missing: bool = True,
        coord_priority: tuple[tuple[str, str], ...] = (
            ("TLON", "TLAT"),
            ("ULON", "ULAT"),
            ("NLON", "NLAT"),
            ("ELON", "ELAT"),
            ("lon", "lat"),
            ("longitude", "latitude"),
        ),
    ) -> tuple[np.ndarray, np.ndarray]:
        if da2.ndim != 2:
            raise ValueError(f"Expected 2D DataArray; got dims={da2.dims}, shape={da2.shape}")
        if (lon_coord_name is not None) or (lat_coord_name is not None):
            if lon_coord_name is None or lat_coord_name is None:
                raise ValueError("Provide both lon_coord_name and lat_coord_name.")
            lon_da = da2.coords[lon_coord_name]
            lat_da = da2.coords[lat_coord_name]
            if lon_da.ndim != 2 or lat_da.ndim != 2:
                raise ValueError("Expected 2D lon/lat coords.")
            if lon_da.dims != da2.dims:
                da2 = da2.transpose(*lon_da.dims)
                lon_da = da2.coords[lon_coord_name]
                lat_da = da2.coords[lat_coord_name]
            return np.asarray(lon_da.data), np.asarray(lat_da.data)
        if infer_if_missing:
            for xnm, ynm in coord_priority:
                if (xnm in da2.coords) and (ynm in da2.coords):
                    lon_da = da2.coords[xnm]
                    lat_da = da2.coords[ynm]
                    if lon_da.ndim == 2 and lat_da.ndim == 2:
                        if lon_da.dims != da2.dims:
                            da2 = da2.transpose(*lon_da.dims)
                            lon_da = da2.coords[xnm]
                            lat_da = da2.coords[ynm]
                        return np.asarray(lon_da.data), np.asarray(lat_da.data)
        raise ValueError(f"Could not resolve 2D lon/lat coords for {da2.name!r}. Available coords: {list(da2.coords)}")

    def pygmt_cice_da_prep(
        self,
        da: xr.DataArray,
        *,
        lon_coord_name: str | None = None,
        lat_coord_name: str | None = None,
        region: tuple[float, float, float, float] | None = None,
        lon_wrap: str = "auto",
        extra_mask=None,
        mask_zero: bool | None = None,
        z_clip: tuple[float, float] | None = None,
        z_range_mask: tuple[float, float] | None = None,
        dtype: str = "float32",
        infer_coords: bool = True,
        return_mask: bool = True,
        return_flat_index: bool = True,
    ) -> dict:
        da2 = da.squeeze(drop=True)
        if da2.ndim != 2:
            raise ValueError(f"Expected 2D DataArray after squeeze; got dims={da2.dims}, shape={da2.shape}")
        if ("nj" in da2.dims) and ("ni" in da2.dims) and (da2.dims != ("nj", "ni")):
            da2 = da2.transpose("nj", "ni")
        lon2d, lat2d = self.resolve_cice_lonlat_2d(
            da2,
            lon_coord_name=lon_coord_name,
            lat_coord_name=lat_coord_name,
            infer_if_missing=infer_coords,
        )
        if lon_wrap == "auto":
            if region is not None:
                xmin, xmax, _, _ = region
                if (xmin < 0.0) or (xmax < 0.0):
                    lon2d = self.normalise_longitudes(lon2d, to="-180-180")
                elif (xmin >= 0.0) and (xmax > 180.0):
                    lon2d = self.normalise_longitudes(lon2d, to="0-360")
        else:
            lon2d = self.normalise_longitudes(lon2d, to=lon_wrap)
        z_data = da2.data
        if self.is_dask_array(z_data):
            z2d = da2.astype(dtype).compute().values
        else:
            z2d = np.asarray(z_data, dtype=dtype)
        if z_clip is not None:
            z2d = np.clip(z2d, z_clip[0], z_clip[1])
        m = np.isfinite(z2d)
        if mask_zero is None:
            mask_zero = self.auto_mask_zero(da2)
        if mask_zero:
            m &= ~np.isclose(z2d, 0.0, atol=1e-8)
        if z_range_mask is not None:
            lo, hi = z_range_mask
            m &= (z2d >= lo) & (z2d <= hi)
        if region is not None:
            xmin, xmax, ymin, ymax = region
            lat_ok = (lat2d >= ymin) & (lat2d <= ymax)
            lon_ok = (lon2d >= xmin) & (lon2d <= xmax) if xmin <= xmax else (lon2d >= xmin) | (lon2d <= xmax)
            m &= lon_ok & lat_ok
        if extra_mask is not None:
            em = extra_mask(da2) if callable(extra_mask) else extra_mask
            em = np.asarray(em.squeeze(drop=True).values if isinstance(em, xr.DataArray) else em, dtype=bool)
            if em.shape != z2d.shape:
                raise ValueError(f"extra_mask shape mismatch: {em.shape} vs {z2d.shape}")
            m &= em
        out = {
            "lon": np.asarray(lon2d, dtype=dtype)[m].ravel(),
            "lat": np.asarray(lat2d, dtype=dtype)[m].ravel(),
            "z": np.asarray(z2d, dtype=dtype)[m].ravel(),
            "shape": z2d.shape,
        }
        if return_mask:
            out["mask2d"] = m
        if return_flat_index:
            out["flat_idx"] = np.flatnonzero(m.ravel())
        return out

    # ------------------------------------------------------------------
    # CICE metrics
    # ------------------------------------------------------------------
    def compute_cice_ice_extent(self, ds: xr.Dataset, *, threshold: float | None = None, time_index: int = 0, area_units_out: str = "million_km2") -> dict:
        threshold = self.sic_threshold if threshold is None else float(threshold)
        da_aice = ds[self.cice_aice_name]
        da_area = ds[self.cice_area_name]
        da_lat = ds[self.cice_lat_name]
        if "time" in da_aice.dims:
            da_aice = da_aice.isel(time=time_index)
        da_aice = da_aice.squeeze(drop=True)
        area2d = da_area.squeeze(drop=True)
        lat2d = da_lat.squeeze(drop=True)
        aice = np.asarray(da_aice.values, dtype=np.float64)
        area = np.asarray(area2d.values, dtype=np.float64)
        lat = np.asarray(lat2d.values, dtype=np.float64)
        valid = np.isfinite(aice) & np.isfinite(area) & np.isfinite(lat)
        icy = valid & (aice >= threshold)
        south = icy & (lat < 0.0)
        north = icy & (lat >= 0.0)
        south_m2 = np.sum(area[south], dtype=np.float64)
        north_m2 = np.sum(area[north], dtype=np.float64)
        global_m2 = south_m2 + north_m2
        if area_units_out == "m2":
            scale, units = 1.0, "m$^2$"
        elif area_units_out == "km2":
            scale, units = 1e-6, "km$^2$"
        elif area_units_out == "million_km2":
            scale, units = 1e-12, "10^6 km^2"
        else:
            raise ValueError("area_units_out must be one of: 'm2', 'km2', 'million_km2'")
        return {
            "south": south_m2 * scale,
            "north": north_m2 * scale,
            "global": global_m2 * scale,
            "units": units,
            "threshold": threshold,
        }

    def compute_cice_area_volume_thickness(self, ds: xr.Dataset, *, time_index: int = 0) -> dict:
        da_hi = ds[self.cice_hi_name]
        da_aice = ds[self.cice_aice_name]
        da_area = ds[self.cice_area_name]
        da_lat = ds[self.cice_lat_name]
        if "time" in da_hi.dims:
            da_hi = da_hi.isel(time=time_index)
        if "time" in da_aice.dims:
            da_aice = da_aice.isel(time=time_index)
        da_hi = da_hi.squeeze(drop=True)
        da_aice = da_aice.squeeze(drop=True)
        da_area = da_area.squeeze(drop=True)
        da_lat = da_lat.squeeze(drop=True)
        hi = np.asarray(da_hi.values, dtype=np.float64)
        aice = np.asarray(da_aice.values, dtype=np.float64)
        area = np.asarray(da_area.values, dtype=np.float64)
        lat = np.asarray(da_lat.values, dtype=np.float64)
        valid = np.isfinite(hi) & np.isfinite(aice) & np.isfinite(area) & np.isfinite(lat)
        valid &= (aice >= 0.0) & (aice <= 1.0) & (hi >= 0.0)
        sia_cell = np.where(valid, aice * area, 0.0)
        siv_cell = np.where(valid, hi * area, 0.0)
        south = lat < 0.0
        north = lat >= 0.0
        def _pack(mask):
            sia = np.sum(sia_cell[mask], dtype=np.float64)
            siv = np.sum(siv_cell[mask], dtype=np.float64)
            sit = siv / sia if sia > 0.0 else np.nan
            return {"SIA": sia * 1e-12, "SIV": siv * 1e-12, "SIT": sit}
        return {
            "south": _pack(south),
            "north": _pack(north),
            "global": _pack(valid),
            "SIA_units": "10^6 km^2",
            "SIV_units": "10^3 km^3",
            "SIT_units": "m",
        }

    @staticmethod
    def format_cice_ice_extent_label(extent_value: float, *, precision: int = 2, units: str = "@[10^6@[ km@[^2@[", prefix: str = "SIE") -> str:
        return f"{prefix}: {extent_value:.{precision}f} {units}"

    @staticmethod
    def format_cice_aggregate_sit_label(sit_value: float, *, precision: int = 2, prefix: str = "Agg. SIT", units: str = "m") -> str:
        return f"{prefix}: {sit_value:.{precision}f} {units}"

    # ------------------------------------------------------------------
    # NSIDC helpers
    # ------------------------------------------------------------------
    @staticmethod
    def get_nsidc_sic_name(ds: xr.Dataset, prefer: str | None = None) -> str:
        candidates = [prefer] if prefer is not None else []
        candidates.extend(["cdr_seaice_conc", "cdr_seaice_conc_monthly", "nsidc_bt_seaice_conc", "nsidc_nt_seaice_conc"])
        for name in candidates:
            if name and name in ds.data_vars:
                return name
        raise KeyError(f"Could not find an NSIDC SIC variable in dataset vars: {list(ds.data_vars)}")

    def get_nsidc_daily_dir(self, hemisphere: str) -> Path:
        hem = hemisphere.strip().lower()
        if hem == "south":
            return self.paths.nsidc_daily_south
        if hem == "north":
            return self.paths.nsidc_daily_north
        raise ValueError("hemisphere must be 'south' or 'north'")

    def get_nsidc_cell_area_path(self, hemisphere: str) -> Path:
        hem = hemisphere.strip().lower()
        if hem == "south":
            return self.paths.nsidc_cell_area_south
        if hem == "north":
            return self.paths.nsidc_cell_area_north
        raise ValueError("hemisphere must be 'south' or 'north'")

    def find_nsidc_daily_file(self, date_str: str, *, hemisphere: str = "south") -> Path:
        root_dir = self.get_nsidc_daily_dir(hemisphere)
        hem_abbrev = "sh" if hemisphere.strip().lower() == "south" else "nh"
        pattern = f"seaice_conc_daily_{hem_abbrev}_{date_str.replace('-', '')}_*.nc"
        matches = sorted(root_dir.glob(pattern))
        if not matches:
            raise FileNotFoundError(f"No NSIDC daily file found for {date_str} in {root_dir} matching {pattern}")
        return matches[-1]

    def load_nsidc_day(self, path_or_str: str | Path, *, sic_name: str | None = None, decode_times: bool = True) -> xr.Dataset:
        ds = xr.open_dataset(
            Path(path_or_str),
            decode_times=decode_times,
            mask_and_scale=True,
            drop_variables=[
                "nsidc_bt_seaice_conc",
                "nsidc_nt_seaice_conc",
                "qa_of_cdr_seaice_conc",
                "spatial_interpolation_flag",
                "stdev_of_cdr_seaice_conc",
                "temporal_interpolation_flag",
            ],
        )
        if "time" in ds.variables and "tdim" in ds.dims:
            ds = ds.set_coords("time")
            ds = ds.swap_dims({"tdim": "time"})
            ds = ds.drop_vars("tdim", errors="ignore")
        for c in ("time", "xgrid", "ygrid"):
            if c in ds.variables:
                ds = ds.set_coords(c)
        sic_name = self.get_nsidc_sic_name(ds, prefer=sic_name or self.nsidc_sic_preference)
        ds[sic_name] = ds[sic_name].where((ds[sic_name] >= 0.0) & (ds[sic_name] <= 1.0))
        return ds

    @staticmethod
    def get_nsidc_proj4(ds: xr.Dataset) -> str:
        if "projection" in ds.variables and "proj4text" in ds["projection"].attrs:
            return ds["projection"].attrs["proj4text"]
        if "crs" in ds.variables and "proj4text" in ds["crs"].attrs:
            return ds["crs"].attrs["proj4text"]
        raise ValueError("Could not determine NSIDC projection from dataset metadata.")

    def get_nsidc_cell_area(self, hemisphere: str) -> xr.DataArray:
        path = self.get_nsidc_cell_area_path(hemisphere)
        ds = xr.open_dataset(path)
        if "cell_area" not in ds:
            raise KeyError(f"No 'cell_area' variable in {path}")
        return ds["cell_area"]

    def compute_nsidc_day_metrics(self, date_str: str, *, hemisphere: str = "south", threshold: float | None = None) -> dict:
        threshold = self.sic_threshold if threshold is None else float(threshold)
        path = self.find_nsidc_daily_file(date_str, hemisphere=hemisphere)
        ds = self.load_nsidc_day(path)
        sic_name = self.get_nsidc_sic_name(ds, prefer=self.nsidc_sic_preference)
        sic = ds[sic_name]
        if "time" in sic.dims:
            sic = sic.isel(time=0)
        sic = sic.squeeze(drop=True)
        area = self.get_nsidc_cell_area(hemisphere)
        sicv = np.asarray(sic.values, dtype=np.float64)
        area_v = np.asarray(area.values, dtype=np.float64)
        valid = np.isfinite(sicv) & np.isfinite(area_v) & (sicv >= 0.0) & (sicv <= 1.0)
        mask = valid & (sicv >= threshold)
        sia = np.sum((sicv * area_v)[mask], dtype=np.float64) * 1e-12
        sie = np.sum(area_v[mask], dtype=np.float64) * 1e-12
        return {"date": date_str, "hemisphere": hemisphere, "SIA": sia, "SIE": sie, "units": "10^6 km^2", "threshold": threshold}

    def build_nsidc_sia_timeseries(self, dt0_str: str, dtN_str: str, *, hemisphere: str) -> xr.Dataset:
        dates = pd.date_range(dt0_str, dtN_str, freq="D")
        vals = []
        for dt in dates:
            date_str = dt.strftime("%Y-%m-%d")
            try:
                vals.append(self.compute_nsidc_day_metrics(date_str, hemisphere=hemisphere)["SIA"])
            except FileNotFoundError:
                vals.append(np.nan)
        return xr.Dataset(
            data_vars={"SIA": ("time", np.asarray(vals, dtype=np.float64))},
            coords={"time": dates.values},
            attrs={"source": "NSIDC G02202 + NSIDC0771 cell area", "hemisphere": hemisphere, "units": "10^6 km^2"},
        )

    def build_cice_sia_timeseries(self, dt0_str: str, dtN_str: str) -> xr.Dataset:
        dates = pd.date_range(dt0_str, dtN_str, freq="D")
        sh = []
        nh = []
        for dt in dates:
            ds = self.load_cice_day(dt.strftime("%Y-%m-%d"))
            stats = self.compute_cice_area_volume_thickness(ds)
            sh.append(stats["south"]["SIA"])
            nh.append(stats["north"]["SIA"])
        return xr.Dataset(
            data_vars={"SIA_SH": ("time", np.asarray(sh, dtype=np.float64)), "SIA_NH": ("time", np.asarray(nh, dtype=np.float64))},
            coords={"time": dates.values},
            attrs={"source": "CICE history", "units": "10^6 km^2"},
        )

    def nsidc_sic_contour_segments(self, ds: xr.Dataset, *, hemisphere: str = "south", threshold: float | None = None, time_index: int = 0, x_name: str = "xgrid", y_name: str = "ygrid", min_vertices: int = 8, max_jump: float = 180.0) -> list[dict]:
        threshold = self.sic_threshold if threshold is None else float(threshold)
        sic_name = self.get_nsidc_sic_name(ds, prefer=self.nsidc_sic_preference)
        da = ds[sic_name]
        if "time" in da.dims:
            da = da.isel(time=time_index)
        da = da.squeeze(drop=True)
        sic = np.asarray(da.values, dtype=np.float64)
        sic = np.where((sic >= 0.0) & (sic <= 1.0), sic, np.nan)
        x = np.asarray(ds[x_name].values, dtype=np.float64)
        y = np.asarray(ds[y_name].values, dtype=np.float64)
        proj4 = self.get_nsidc_proj4(ds)
        crs_nsidc = CRS.from_user_input(proj4)
        crs_geod = crs_nsidc.geodetic_crs if crs_nsidc.geodetic_crs is not None else CRS.from_epsg(4326)
        transformer = Transformer.from_crs(crs_nsidc, crs_geod, always_xy=True)
        fig_tmp, ax_tmp = plt.subplots()
        try:
            cs = ax_tmp.contour(x, y, sic, levels=[threshold])
            all_segments = []
            if not cs.allsegs or not cs.allsegs[0]:
                return all_segments
            hemi = hemisphere.strip().lower()
            for seg_xy in cs.allsegs[0]:
                if seg_xy.shape[0] < min_vertices:
                    continue
                xp, yp = seg_xy[:, 0], seg_xy[:, 1]
                lon, lat = transformer.transform(xp, yp)
                lon = self.normalise_longitudes(lon, to=self.lon_wrap)
                keep = lat <= 0.0 if hemi == "south" else lat >= 0.0
                lon, lat = lon[keep], lat[keep]
                if lon.size < min_vertices:
                    continue
                all_segments.extend(self.split_line_by_longitude_jump(lon, lat, max_jump=max_jump, min_points=min_vertices))
            return all_segments
        finally:
            plt.close(fig_tmp)

    def plot_nsidc_segments(self, fig: pygmt.Figure, segments: list[dict], *, pen: str | None = None):
        pen = self.nsidc_pen if pen is None else pen
        for seg in segments:
            fig.plot(x=seg["lon"], y=seg["lat"], pen=pen)

    # ------------------------------------------------------------------
    # PyGMT figure pieces
    # ------------------------------------------------------------------
    @staticmethod
    def pygmt_basemap(
        fig: pygmt.Figure,
        *,
        region=(0, 360, -90, -60),
        projection="S0/-90/20c",
        frame=("af",),
        coast: bool = True,
        land: str = "gray85",
        water: str = "white",
        shorelines: str = "0.35p,black",
    ) -> pygmt.Figure:
        fig.basemap(region=region, projection=projection, frame=frame)
        if coast:
            fig.coast(region=region, projection=projection, land=land, water=water, shorelines=shorelines)
        return fig

    def add_sia_timeseries_panel(
        self,
        fig: pygmt.Figure,
        *,
        cice_ts: xr.Dataset,
        nsidc_sh_ts: xr.Dataset | None = None,
        nsidc_nh_ts: xr.Dataset | None = None,
        current_date: str | None = None,
        position: str = "JTR+w15c/5c+o0.3c/0.3c",
    ):
        times = pd.to_datetime(cice_ts.time.values)
        t0 = times.min().strftime("%Y-%m-%d")
        t1 = times.max().strftime("%Y-%m-%d")
        y_series = [np.nanmax(cice_ts["SIA_SH"].values), np.nanmax(cice_ts["SIA_NH"].values)]
        if nsidc_sh_ts is not None:
            y_series.append(np.nanmax(nsidc_sh_ts["SIA"].values))
        if nsidc_nh_ts is not None:
            y_series.append(np.nanmax(nsidc_nh_ts["SIA"].values))
        ymax = float(np.nanmax(y_series)) * 1.1
        with fig.inset(position=position, box="+gwhite@60+p0.5p"):
            fig.basemap(region=[t0, t1, 0, ymax], projection="X15c/5c", frame=["xaf", "yaf+lSIA (10^6 km^2)"])
            fig.plot(x=times, y=cice_ts["SIA_SH"].values, pen="1.2p,blue")
            fig.plot(x=times, y=cice_ts["SIA_NH"].values, pen="1.2p,red")
            if nsidc_sh_ts is not None:
                fig.plot(x=pd.to_datetime(nsidc_sh_ts.time.values), y=nsidc_sh_ts["SIA"].values, pen="1.0p,green")
            if nsidc_nh_ts is not None:
                fig.plot(x=pd.to_datetime(nsidc_nh_ts.time.values), y=nsidc_nh_ts["SIA"].values, pen="1.0p,orange")
            if current_date is not None:
                fig.plot(x=[pd.Timestamp(current_date), pd.Timestamp(current_date)], y=[0, ymax], pen="0.8p,black,--")

    # ------------------------------------------------------------------
    # High-level day plots
    # ------------------------------------------------------------------
    def plot_aice_day(
        self,
        date_str: str,
        *,
        add_nsidc_south: bool = True,
        add_nsidc_north: bool = False,
        add_sia_timeseries: bool = False,
        ts_start: str | None = None,
        ts_end: str | None = None,
        output_path: str | Path | None = None,
        show: bool = False,
    ) -> pygmt.Figure:
        ds = self.load_cice_day(date_str)
        dt_str = self.cice_corrected_datestr(ds)
        da = ds[self.cice_aice_name]
        da_plt = self.pygmt_cice_da_prep(da, lon_wrap=self.lon_wrap)
        ext = self.compute_cice_ice_extent(ds)
        sh_txt = self.format_cice_ice_extent_label(ext["south"])
        nh_txt = self.format_cice_ice_extent_label(ext["north"])
        nsidc_sh_segments = []
        nsidc_nh_segments = []
        if add_nsidc_south:
            nsidc_sh = self.load_nsidc_day(self.find_nsidc_daily_file(dt_str, hemisphere="south"))
            nsidc_sh_segments = self.nsidc_sic_contour_segments(nsidc_sh, hemisphere="south")
        if add_nsidc_north:
            nsidc_nh = self.load_nsidc_day(self.find_nsidc_daily_file(dt_str, hemisphere="north"))
            nsidc_nh_segments = self.nsidc_sic_contour_segments(nsidc_nh, hemisphere="north")
        fig = pygmt.Figure()
        with pygmt.config(**self.pygmt_config):
            self.pygmt_basemap(fig, region=self.south_region, projection=self.south_projection, frame=["af", f"+t{dt_str}"])
            pygmt.makecpt(cmap=self.cmap_aice, series=[0, 1])
            fig.plot(x=da_plt["lon"], y=da_plt["lat"], style=self.point_style, fill=da_plt["z"], cmap=True)
            if nsidc_sh_segments:
                self.plot_nsidc_segments(fig, nsidc_sh_segments)
            fig.text(position="BL", text=sh_txt, justify="CM", offset="4c/-1c", font="16p,Helvetica-Bold,black", fill="white@35", pen="0.5p,black", no_clip=True)
            fig.shift_origin(xshift="1w+1.5c")
            self.pygmt_basemap(fig, region=self.north_region, projection=self.north_projection, frame=("af",))
            fig.plot(x=da_plt["lon"], y=da_plt["lat"], style=self.point_style, fill=da_plt["z"], cmap=True)
            if nsidc_nh_segments:
                self.plot_nsidc_segments(fig, nsidc_nh_segments)
            fig.text(position="BR", text=nh_txt, justify="CM", offset="-4c/-1c", font="16p,Helvetica-Bold,black", fill="white@35", pen="0.5p,black", no_clip=True)
            if add_sia_timeseries:
                if ts_start is None or ts_end is None:
                    raise ValueError("ts_start and ts_end are required when add_sia_timeseries=True")
                cice_ts = self.build_cice_sia_timeseries(ts_start, ts_end)
                nsidc_sh_ts = self.build_nsidc_sia_timeseries(ts_start, ts_end, hemisphere="south")
                nsidc_nh_ts = self.build_nsidc_sia_timeseries(ts_start, ts_end, hemisphere="north") if self.paths.nsidc_daily_north.exists() else None
                self.add_sia_timeseries_panel(fig, cice_ts=cice_ts, nsidc_sh_ts=nsidc_sh_ts, nsidc_nh_ts=nsidc_nh_ts, current_date=dt_str)
        fig.colorbar(position="JBC+w12c/1c+mc+h+o-11c/1c", frame=["xaf+l@[\\texttt{aice}@[", "y+l1/100"], cmap=True)
        if output_path is not None:
            fig.savefig(str(output_path))
        if show:
            fig.show()
        return fig

    def plot_hi_day(
        self,
        date_str: str,
        *,
        output_path: str | Path | None = None,
        show: bool = False,
    ) -> pygmt.Figure:
        ds = self.load_cice_day(date_str)
        dt_str = self.cice_corrected_datestr(ds)
        da = ds[self.cice_hi_name]
        da_plt = self.pygmt_cice_da_prep(da, lon_wrap=self.lon_wrap)
        sit_stats = self.compute_cice_area_volume_thickness(ds)
        sh_txt = self.format_cice_aggregate_sit_label(sit_stats["south"]["SIT"], units=sit_stats["SIT_units"])
        nh_txt = self.format_cice_aggregate_sit_label(sit_stats["north"]["SIT"], units=sit_stats["SIT_units"])
        fig = pygmt.Figure()
        with pygmt.config(**self.pygmt_config):
            self.pygmt_basemap(fig, region=self.south_region, projection=self.south_projection, frame=["af", f"+t{dt_str}"])
            pygmt.makecpt(cmap=self.cmap_hi, series=list(self.hi_range))
            fig.plot(x=da_plt["lon"], y=da_plt["lat"], style=self.point_style, fill=da_plt["z"], cmap=True)
            fig.text(position="BL", text=sh_txt, justify="CM", offset="4c/-1c", font="16p,Helvetica-Bold,black", fill="white@35", pen="0.5p,black", no_clip=True)
            fig.shift_origin(xshift="1w+1.5c")
            self.pygmt_basemap(fig, region=self.north_region, projection=self.north_projection, frame=("af",))
            fig.plot(x=da_plt["lon"], y=da_plt["lat"], style=self.point_style, fill=da_plt["z"], cmap=True)
            fig.text(position="BR", text=nh_txt, justify="CM", offset="-4c/-1c", font="16p,Helvetica-Bold,black", fill="white@35", pen="0.5p,black", no_clip=True)
        fig.colorbar(position="JBC+w12c/1c+mc+h+o-11c/1c", frame=["xaf+l@[\\texttt{hi}@[", "y+lm"], cmap=True)
        if output_path is not None:
            fig.savefig(str(output_path))
        if show:
            fig.show()
        return fig

    # ------------------------------------------------------------------
    # Animation helpers
    # ------------------------------------------------------------------
    def render_frames(
        self,
        *,
        dt0_str: str,
        dtN_str: str,
        variable: str = "aice",
        add_sia_timeseries: bool = False,
    ) -> list[Path]:
        frame_dir = self.paths.animation_dir / f"{variable}_{dt0_str}_{dtN_str}"
        frame_dir.mkdir(parents=True, exist_ok=True)
        frame_paths: list[Path] = []
        for dt in pd.date_range(dt0_str, dtN_str, freq="D"):
            date_str = dt.strftime("%Y-%m-%d")
            frame_path = frame_dir / f"frame_{date_str}.png"
            if variable == "aice":
                self.plot_aice_day(date_str, add_sia_timeseries=add_sia_timeseries, ts_start=dt0_str if add_sia_timeseries else None, ts_end=dtN_str if add_sia_timeseries else None, output_path=frame_path)
            elif variable == "hi":
                self.plot_hi_day(date_str, output_path=frame_path)
            else:
                raise ValueError("variable must be 'aice' or 'hi'")
            frame_paths.append(frame_path)
        return frame_paths

    def create_animation(
        self,
        *,
        dt0_str: str,
        dtN_str: str,
        variable: str = "aice",
        output_path: str | Path | None = None,
        fps: int = 4,
        add_sia_timeseries: bool = False,
        codec: str = "gif",
    ) -> Path:
        frame_paths = self.render_frames(dt0_str=dt0_str, dtN_str=dtN_str, variable=variable, add_sia_timeseries=add_sia_timeseries)
        if output_path is None:
            suffix = ".gif" if codec == "gif" else ".mp4"
            output_path = self.paths.animation_dir / f"{variable}_{dt0_str}_{dtN_str}{suffix}"
        output_path = Path(output_path)
        if codec == "gif":
            frames = [imageio.imread(p) for p in frame_paths]
            imageio.mimsave(output_path, frames, fps=fps)
        elif codec == "mp4":
            with imageio.get_writer(output_path, fps=fps) as writer:
                for p in frame_paths:
                    writer.append_data(imageio.imread(p))
        else:
            raise ValueError("codec must be 'gif' or 'mp4'")
        return output_path
