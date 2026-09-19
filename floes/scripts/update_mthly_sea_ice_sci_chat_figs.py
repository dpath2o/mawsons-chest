#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import sys
import traceback
from pathlib import Path
THIS = Path(__file__).resolve()
FLOES_ROOT = THIS.parents[1]
PARENT = FLOES_ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))
from floes.config import default_config, previous_complete_month  # noqa: E402
from floes.observations.bremen import BremenSeaIceReader  # noqa: E402
from floes.observations.era5 import ERA5Reader  # noqa: E402
from floes.observations.esa_cci import ESACCISITReader  # noqa: E402
from floes.observations.nsidc import NSIDCReader  # noqa: E402
from floes.observations.ocean import OceanReader  # noqa: E402
from floes.observations.oisst import OISSTReader  # noqa: E402
from floes.observations.sea_ice import annual_sie_maximum  # noqa: E402
from floes.plotting.gallery import GalleryFigure, write_gallery  # noqa: E402
from floes.plotting.monthly import MonthlySeaIceChatPlotter  # noqa: E402
from floes.plotting.nsidc_diagnostics import NSIDCDiagnosticPlotter  # noqa: E402

def _actual_ym(obj, fallback_year: int, fallback_month: int) -> tuple[int, int, bool]:
    attrs = getattr(obj, "attrs", {})
    return (int(attrs.get("selected_year", fallback_year)),
            int(attrs.get("selected_month", fallback_month)),
            bool(attrs.get("exact_requested_month", True)))

def _recent_months(year: int, month: int, count: int = 3) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    y, m = int(year), int(month)
    for _ in range(count):
        out.append((y, m))
        m -= 1
        if m == 0:
            y -= 1
            m = 12
    return list(reversed(out))

def _previous_months(year: int, month: int, count: int = 3) -> list[tuple[int, int]]:
    y, m = int(year), int(month)
    m -= 1
    if m == 0:
        y -= 1
        m = 12
    return _recent_months(y, m, count)

def _history_table(paths: dict[tuple[int, int], Path], *, anchor_year: int, anchor_month: int, prefix: str) -> str:
    """Return a rolling 3-month x 3-year Markdown link table."""
    month_columns = _previous_months(anchor_year, anchor_month, 3)
    headers = [f"{month:02d}" for _, month in month_columns]
    lines = ["", "**Rolling three-month / three-year archive**", "", "| Year | " + " | ".join(headers) + " |", "| --- | " + " | ".join(["---"] * len(headers)) + " |"]
    for offset in (2, 1, 0):
        row_anchor = anchor_year - offset
        row_months = _previous_months(row_anchor, anchor_month, 3)
        cells: list[str] = []
        for year, month in row_months:
            path = paths.get((year, month))
            if path is None:
                cells.append("—")
            else:
                rel = f"../figs/mthly_sea_ice_sci_chat/{path.name}"
                cells.append(f"[{year:04d}-{month:02d}]({rel})")
        lines.append(f"| {row_anchor} | " + " | ".join(cells) + " |")
    return "\n".join(lines)

def _run_step(name: str, func, *, keep_going: bool, manifest: dict, verbose: bool):
    print(f"\n=== {name} ===", flush=True)
    try:
        result = func()
        manifest["steps"][name] = {"status": "ok", "result": str(result) if result is not None else None}
        print(f"OK: {name}", flush=True)
        return result
    except Exception as exc:  # noqa: BLE001
        manifest["steps"][name] = {"status": "skipped_or_failed", "error": repr(exc)}
        print(f"SKIP/FAIL: {name}: {exc}", flush=True)
        if verbose:
            traceback.print_exc()
        if not keep_going:
            raise
        return None

def main(argv: list[str] | None = None) -> int:
    default_year, default_month = previous_complete_month()
    p = argparse.ArgumentParser(description="Generate monthly sea-ice science-chat figures using floes.")
    p.add_argument("--project", default="gv90", help="Gadi project for scratch/cache defaults.")
    p.add_argument("--user", default=None, help="Gadi username. Defaults to $USER inside FloesConfig.")
    p.add_argument("--gadi-base", type=Path, default=Path("/g/data/gv90/wrh581"), help="Base directory containing known observational resources.")
    p.add_argument("--era5-root", type=Path, default=Path("/g/data/rt52"), help="Root containing the official era5/ and near-real-time era5t/ collections.")
    p.add_argument("--seaice-root", type=Path, default=Path("/g/data/gv90/da1339/SeaIce"), help="Local archive for NSIDC, University of Bremen and ESA CCI sea-ice products.")
    p.add_argument("--fig-dir", type=Path, default=None, help="Figure output directory.")
    p.add_argument("--docs-dir", type=Path, default=None, help="Documentation/gallery output directory.")
    p.add_argument("--year", type=int, default=default_year)
    p.add_argument("--month", type=int, default=default_month)
    p.add_argument("--clim-start", type=int, default=1979)
    p.add_argument("--clim-end", type=int, default=2008)
    p.add_argument("--will-clim-start", type=int, default=1979, help="Start year for legacy Will Hobbs diagnostics.")
    p.add_argument("--will-clim-end", type=int, default=2018, help="End year for legacy Will Hobbs diagnostics.")
    p.add_argument("--comparison-split-year", type=int, default=2005, help="Year separating black/red points in hemispheric comparisons.")
    p.add_argument("--nsidc-daily-base", type=Path, default=Path("/g/data/gv90/da1339/SeaIce"), help=("Base for NSIDC daily fallbacks. Local G02202 V6 gridded daily aggregates "
                                                                                                      "are read from --seaice-root first; this keeps NSIDC processing on the "
                                                                                                      "da1339 archive rather than the legacy wrh581 archive."))
    p.add_argument("--skip-will-suite", action="store_true", help="Skip the legacy NSIDC diagnostic reproductions.")
    p.add_argument("--strict", action="store_true", help="Fail on first missing optional product.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)
    cfg = default_config(project=args.project,
                         user=args.user,
                         gadi_base=args.gadi_base,
                         seaice_root=args.seaice_root,
                         era5_root=args.era5_root,
                         output_root=args.fig_dir,
                         docs_root=args.docs_dir,
                         climatology_start=args.clim_start,
                         climatology_end=args.clim_end)
    cfg.figure_root.mkdir(parents=True, exist_ok=True)
    cfg.markdown_gallery.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"requested_year": args.year,
                "requested_month": args.month,
                "gadi_base": str(cfg.gadi_base),
                "seaice_root": str(cfg.seaice_root),
                "era5_root": str(cfg.era5_root),
                "nsidc_daily_base": str(args.nsidc_daily_base),
                "figure_root": str(cfg.figure_root),
                "gallery": str(cfg.markdown_gallery),
                "steps": {}}
    print("floes monthly science-chat update")
    print(f"Requested month: {args.year:04d}-{args.month:02d}")
    print("Note           : if that month is unavailable, map products fall back to latest available <= requested month.")
    print(f"Gadi base      : {cfg.gadi_base}")
    print(f"Sea-ice root   : {cfg.seaice_root}")
    print(f"ERA5 root      : {cfg.era5_root}")
    print(f"NSIDC daily    : {args.nsidc_daily_base}")
    print(f"Figure dir     : {cfg.figure_root}")
    print(f"Gallery        : {cfg.markdown_gallery}")
    print("Acquisition    : disabled in processing job; run qsub ./download_observations.pbs first")

    if args.dry_run:
        print("Dry run only; no figures generated.")
        return 0

    keep_going = not args.strict
    plotter = MonthlySeaIceChatPlotter(cfg)
    nsidc = NSIDCReader(cfg, hemisphere="SH", daily_base=args.nsidc_daily_base)
    bremen = BremenSeaIceReader(cfg)
    esa_cci = ESACCISITReader(cfg)
    monthly_totals: dict[str, object] = {}
    daily_totals: dict[str, object] = {}
    map_sic_cache: dict[tuple[int, int, bool], object] = {}
    bremen_cache: dict[tuple[int, int], object] = {}
    nsidc_history: dict[tuple[int, int], Path] = {}
    bremen_history: dict[tuple[int, int], Path] = {}
    esa_history: dict[tuple[int, int], Path] = {}
    era5_history: dict[tuple[int, int], Path] = {}

    def daily_for_sh():
        if "SH" not in daily_totals:
            print("Computing NSIDC SH daily total SIA/SIE ...", flush=True)
            daily_totals["SH"] = nsidc.daily_total_sia_sie().compute()
        return daily_totals["SH"]

    def map_sic_for(year: int, month: int, *, fallback_latest: bool):
        key = (int(year), int(month), bool(fallback_latest))
        if key not in map_sic_cache:
            map_sic_cache[key] = nsidc.sic_month_and_climatology(year=year, month=month, fallback_latest=fallback_latest).compute()
        return map_sic_cache[key]

    def total_for(hemisphere: str):
        hemisphere = hemisphere.upper()
        if hemisphere not in monthly_totals:
            print(f"Computing NSIDC {hemisphere} monthly total SIA/SIE ...", flush=True)
            monthly_totals[hemisphere] = NSIDCReader(cfg, hemisphere=hemisphere).total_sia_sie().compute()
        return monthly_totals[hemisphere]

    def latest_map_sic():
        return map_sic_for(args.year, args.month, fallback_latest=True)

    def ice_edge_for(year: int, month: int):
        latest = latest_map_sic()
        latest_year, latest_month, _ = _actual_ym(latest, args.year, args.month)
        if (year, month) == (latest_year, latest_month):
            return latest["sic"]
        return map_sic_for(year, month, fallback_latest=False)["sic"]

    def bremen_edge_for(year: int, month: int):
        key = (int(year), int(month))
        if key not in bremen_cache:
            bremen_cache[key] = bremen.month(year=year, month=month, fallback_latest=False).compute()
        return bremen_cache[key]

    def comparison_edges(year: int, month: int):
        edges = [(ice_edge_for(year, month), "1.0p,black")]
        try:
            edges.append((bremen_edge_for(year, month), "1.0p,orange,-"))
        except Exception as exc:  # noqa: BLE001 - Bremen is an independent optional comparison
            print(f"WARNING: Bremen SIE edge unavailable for {year:04d}-{month:02d}: {exc}")
        return edges

    def nsidc_sic_map_for(year: int, month: int, *, fallback_latest: bool = False):
        ds = map_sic_for(year, month, fallback_latest=fallback_latest)
        y, m, exact = _actual_ym(ds, args.year, args.month)
        if fallback_latest and not exact:
            print(f"Using latest available NSIDC month {y:04d}-{m:02d} for requested {args.year:04d}-{args.month:02d}.")
        out = cfg.figure_root / f"NSIDC_SH_sic_anomaly_{y:04d}{m:02d}.png"
        return plotter.plot_sic_anomaly_map(ds, year=y, month=m, output=out, stride=2)

    def nsidc_sic_map():
        return nsidc_sic_map_for(args.year, args.month, fallback_latest=True)

    def nsidc_history_maps():
        anchor = latest_map_sic()
        anchor_year, anchor_month, _ = _actual_ym(anchor, args.year, args.month)
        for offset in range(3):
            for year, month in _previous_months(anchor_year - offset, anchor_month, 3):
                try:
                    nsidc_history[(year, month)] = Path(nsidc_sic_map_for(year, month))
                except Exception as exc:  # noqa: BLE001
                    print(f"WARNING: NSIDC history map unavailable for {year:04d}-{month:02d}: {exc}")
        return len(nsidc_history)

    def nsidc_sia_ts():
        ds = total_for("SH")
        nc = cfg.figure_root / "NSIDC_SH_total_SIA_SIE_monthly.nc"
        ds.to_netcdf(nc)
        out = cfg.figure_root / "NSIDC_SH_total_SIA_SIE_monthly.png"
        return plotter.plot_total_sia_sie(ds, output=out)

    def bremen_sic_map_for(year: int, month: int, *, fallback_latest: bool = False):
        da = bremen.month(year=year, month=month, fallback_latest=fallback_latest).compute()
        y, m, exact = _actual_ym(da, args.year, args.month)
        if fallback_latest and not exact:
            print(
                f"Using latest available Bremen SIC month {y:04d}-{m:02d} "
                f"for requested {args.year:04d}-{args.month:02d}."
            )
        out = cfg.figure_root / f"BREMEN_AMSR2_SH_sic_SIE_{y:04d}{m:02d}.png"
        return plotter.plot_gridded_anomaly(da,
                                            output=out,
                                            title=f"{y:04d}-{m:02d}",
                                            cpt="cmocean/ice",
                                            value_range=(0.0, 1.0),
                                            colorbar_label="sea-ice concentration",
                                            colorbar_unit="fraction",
                                            ice_edges=[(ice_edge_for(y, m), "1.0p,black"),(da, "1.0p,orange")],
                                            stride=2)

    def bremen_processed_products():
        processed = bremen.root / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        monthly_path = processed / "BREMEN_AMSR2_SH_SIC_monthly.nc"
        totals_path = processed / "BREMEN_AMSR2_SH_SIA_SIE_daily.nc"
        sic = bremen.sic()
        sic.resample(time="MS").mean(skipna=True).to_dataset(name="sic").to_netcdf(monthly_path)
        bremen.total_sia_sie().to_netcdf(totals_path)
        return f"{monthly_path}; {totals_path}"

    def bremen_sic_map():
        return bremen_sic_map_for(args.year, args.month, fallback_latest=True)

    def bremen_history_maps():
        main = bremen.month(year=args.year, month=args.month, fallback_latest=True)
        anchor_year, anchor_month, _ = _actual_ym(main, args.year, args.month)
        for offset in range(3):
            for year, month in _previous_months(anchor_year - offset, anchor_month, 3):
                try:
                    bremen_history[(year, month)] = Path(bremen_sic_map_for(year, month))
                except Exception as exc:  # noqa: BLE001
                    print(f"WARNING: Bremen history map unavailable for {year:04d}-{month:02d}: {exc}")
        return len(bremen_history)

    def esa_cci_sit_map_for(year: int, month: int, *, fallback_latest: bool = False):
        da = esa_cci.month(year=year, month=month, fallback_latest=fallback_latest).compute()
        y, m, exact = _actual_ym(da, args.year, args.month)
        if fallback_latest and not exact:
            print(f"Using latest available ESA CCI L3C SIT month {y:04d}-{m:02d} "
                  f"for requested {args.year:04d}-{args.month:02d}.")
        out = cfg.figure_root / f"ESA_CCI_L3C_SH_sit_{y:04d}{m:02d}.png"
        return plotter.plot_gridded_anomaly(
            da,
            output=out,
            title=f"{y:04d}-{m:02d}",
            cpt="cmocean/thermal",
            value_range=(0.0, 3.0),
            colorbar_label="sea-ice thickness",
            colorbar_unit="m",
            ice_edge=ice_edge_for(y, m),
            stride=2,
        )

    nsidc_sic_path = _run_step("NSIDC SIC anomaly map", nsidc_sic_map, keep_going=keep_going, manifest=manifest, verbose=args.verbose)

    def esa_cci_sit_map():
        return esa_cci_sit_map_for(args.year, args.month, fallback_latest=True)

    def esa_history_maps():
        main = esa_cci.month(year=args.year, month=args.month, fallback_latest=True)
        anchor_year, anchor_month, _ = _actual_ym(main, args.year, args.month)
        for offset in range(3):
            for year, month in _previous_months(anchor_year - offset, anchor_month, 3):
                try:
                    esa_history[(year, month)] = Path(esa_cci_sit_map_for(year, month))
                except Exception as exc:  # noqa: BLE001
                    print(f"WARNING: ESA CCI history map unavailable for {year:04d}-{month:02d}: {exc}")
        return len(esa_history)

    _run_step("NSIDC total SIA/SIE time series", nsidc_sia_ts, keep_going=keep_going, manifest=manifest, verbose=args.verbose)
    _run_step("Process University of Bremen SIC/SIA/SIE", bremen_processed_products, keep_going=True, manifest=manifest, verbose=args.verbose)
    bremen_sic_path = _run_step("University of Bremen AMSR2 SIC/SIE map", bremen_sic_map, keep_going=True, manifest=manifest, verbose=args.verbose)
    esa_sit_path = _run_step("ESA CCI L3C SIT map", esa_cci_sit_map, keep_going=True, manifest=manifest, verbose=args.verbose)

    will_sia_path = None
    will_sie_by_year_path = None
    will_sie_max_path = None
    will_hemisphere_paths = None

    _run_step(
        "NSIDC rolling map archive",
        nsidc_history_maps,
        keep_going=True,
        manifest=manifest,
        verbose=args.verbose,
    )

    _run_step(
        "Bremen rolling map archive",
        bremen_history_maps,
        keep_going=True,
        manifest=manifest,
        verbose=args.verbose,
    )

    _run_step(
        "ESA CCI rolling map archive",
        esa_history_maps,
        keep_going=True,
        manifest=manifest,
        verbose=args.verbose,
    )

    if not args.skip_will_suite:
        diagnostics = NSIDCDiagnosticPlotter(
            climatology_start=args.will_clim_start,
            climatology_end=args.will_clim_end,
            comparison_split_year=args.comparison_split_year,
        )

        def will_sia_anomaly():
            daily = daily_for_sh()
            return diagnostics.plot_daily_anomalies_by_year(
                daily["SIA"],
                output=cfg.figure_root / "NSIDC_SH_SIA_daily_anomalies_last20yr.png",
                quantity="area",
            )

        def will_sia_standardised_anomaly():
            ds = total_for("SH")
            return diagnostics.plot_monthly_anomaly_timeseries(
                ds["SIA"],
                output=cfg.figure_root / "NSIDC_SIA_cdr_monthly_tplot_standardised.png",
                standardised=True,
                highlight_year=args.year,
            )

        def will_hemisphere_comparison():
            sh = total_for("SH")
            nh = total_for("NH")
            nh.to_netcdf(cfg.figure_root / "NSIDC_NH_total_SIA_SIE_monthly.nc")
            return diagnostics.plot_hemisphere_comparison(
                sh,
                nh,
                annual_output=cfg.figure_root / "NSIDC_Arctic_vs_Antarctic_annual.png",
                monthly_output=cfg.figure_root / "NSIDC_Arctic_vs_Antarctic_monthly_anomalies.png",
            )

        def will_sie_anomalies_by_year():
            daily = daily_for_sh()
            return diagnostics.plot_daily_anomalies_by_year(
                daily["SIE"],
                output=cfg.figure_root / "NSIDC_SH_SIE_daily_anomalies_last20yr.png",
                quantity="extent",
            )

        def will_sie_maximum():
            daily = daily_for_sh()
            daily.to_netcdf(cfg.figure_root / "NSIDC_SH_total_SIA_SIE_daily.nc")
            maxima = annual_sie_maximum(daily["SIE"])
            maxima.to_netcdf(cfg.figure_root / "NSIDC_SH_SIE_annual_maximum.nc")
            return diagnostics.plot_sie_maximum_vs_day(
                maxima,
                output=cfg.figure_root / "NSIDC_SIEmax_vs_day-of-max.png",
                current_year=args.year,
            )

        will_sia_path = _run_step(
            "Will: SH daily SIA anomalies",
            will_sia_anomaly,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )
        _run_step(
            "Will: SH standardised monthly SIA anomaly",
            will_sia_standardised_anomaly,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )
        will_hemisphere_paths = _run_step(
            "Will: Arctic-Antarctic SIE comparison",
            will_hemisphere_comparison,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )
        will_sie_by_year_path = _run_step(
            "Will: SH daily SIE anomalies by year",
            will_sie_anomalies_by_year,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )
        will_sie_max_path = _run_step(
            "Will: SH SIE maximum versus date",
            will_sie_maximum,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )

    def oisst_map():
        sic = latest_map_sic()
        target_year, target_month, _ = _actual_ym(sic, args.year, args.month)
        da = OISSTReader(cfg).anomaly_field(year=target_year, month=target_month, fallback_latest=True)
        y, m, exact = _actual_ym(da, target_year, target_month)
        if not exact:
            print(
                f"Using latest available OISST month {y:04d}-{m:02d} "
                f"for requested {target_year:04d}-{target_month:02d}."
            )
        out = cfg.figure_root / f"OISST_global_sst_anomaly_{y:04d}{m:02d}.png"
        return plotter.plot_gridded_anomaly(
            da,
            output=out,
            title=f"{y:04d}-{m:02d}",
            cpt="polar",
            value_range=(-2.0, 2.0),
            colorbar_label="SST anomaly",
            colorbar_unit="degC",
            ice_edges=comparison_edges(y, m),
        )

    def era5_wind_map_for(year: int, month: int, *, fallback_latest: bool = False):
        sic = latest_map_sic()
        target_year, target_month = int(year), int(month)
        fields = ERA5Reader(cfg).wind_mslp_month(
            year=target_year,
            month=target_month,
            fallback_latest=fallback_latest,
        )
        y, m, exact = _actual_ym(fields, target_year, target_month)
        if not exact:
            print(
                f"Using latest available ERA5 wind month {y:04d}-{m:02d} "
                f"for requested {target_year:04d}-{target_month:02d}."
            )
        out = cfg.figure_root / f"ERA5_wind_SIE_SH_{y:04d}{m:02d}.png"
        return plotter.plot_gridded_anomaly(
            fields["wind_speed"],
            output=out,
            title=f"{y:04d}-{m:02d}",
            cpt="cmocean/speed",
            value_range=(0.0, 30.0),
            colorbar_label="wind speed",
            colorbar_unit="m/s",
            ice_edges=comparison_edges(y, m),
            contour=fields["mslp"],
            contour_interval=4.0,
            contour_annotation=8.0,
            contour_pen="0.45p,gray40",
        )

    def era5_wind_map():
        sic = latest_map_sic()
        target_year, target_month, _ = _actual_ym(sic, args.year, args.month)
        return era5_wind_map_for(target_year, target_month, fallback_latest=True)

    def era5_history_maps():
        sic = latest_map_sic()
        anchor_year, anchor_month, _ = _actual_ym(sic, args.year, args.month)
        for offset in range(3):
            for year, month in _previous_months(anchor_year - offset, anchor_month, 3):
                try:
                    era5_history[(year, month)] = Path(era5_wind_map_for(year, month))
                except Exception as exc:  # noqa: BLE001
                    print(f"WARNING: ERA5 history map unavailable for {year:04d}-{month:02d}: {exc}")
        return len(era5_history)

    def oras_hovmoller_scaffold():
        reader = OceanReader(cfg)
        da = reader.read(
            src="ORAS5",
            var="votemper",
            start_year=max(args.year - 5, 1979),
            end_year=args.year,
            latmin=-80,
            latmax=-45,
            zmin=0,
            zmax=1000,
            allow_latest=True,
        )
        zdim = next((d for d in ("deptht", "depth", "depth_std", "lev") if d in da.dims), None)
        exclude = {"time"}
        if zdim:
            exclude.add(zdim)
        spatial_dims = [d for d in da.dims if d not in exclude]
        hov = da.mean(dim=spatial_dims, skipna=True) if spatial_dims else da
        nc = cfg.figure_root / "ORAS5_votemper_depth_time_SH_latest.nc"
        hov.to_netcdf(nc)
        return nc

    def en4_hovmoller_scaffold():
        reader = OceanReader(cfg)
        da = reader.read(
            src="EN4",
            var="temperature",
            start_year=max(args.year - 5, 1979),
            end_year=args.year,
            latmin=-80,
            latmax=-45,
            zmin=0,
            zmax=1000,
            allow_latest=True,
        )
        zdim = next((d for d in ("depth", "deptht", "depth_std", "lev") if d in da.dims), None)
        exclude = {"time"}
        if zdim:
            exclude.add(zdim)
        spatial_dims = [d for d in da.dims if d not in exclude]
        hov = da.mean(dim=spatial_dims, skipna=True) if spatial_dims else da
        nc = cfg.figure_root / "EN4_temperature_depth_time_SH_latest.nc"
        hov.to_netcdf(nc)
        return nc

    oisst_path = _run_step("OISST SST anomaly map", oisst_map, keep_going=True, manifest=manifest, verbose=args.verbose)
    era5_path = _run_step("ERA5 wind map", era5_wind_map, keep_going=True, manifest=manifest, verbose=args.verbose)
    _run_step("ERA5 rolling map archive", era5_history_maps, keep_going=True, manifest=manifest, verbose=args.verbose)
    _run_step("ORAS5 depth-time diagnostic", oras_hovmoller_scaffold, keep_going=True, manifest=manifest, verbose=args.verbose)
    _run_step("EN4 depth-time diagnostic", en4_hovmoller_scaffold, keep_going=True, manifest=manifest, verbose=args.verbose)

    gallery_figures: list[GalleryFigure] = []
    if will_sie_by_year_path:
        gallery_figures.append(
            GalleryFigure(
                Path(will_sie_by_year_path),
                "Daily Southern Hemisphere SIE Anomalies",
                caption=(
                    "Daily NSIDC G02202 V6 SIE anomalies relative to the 1979–2018 40-year calendar-day "
                    "climatology (29 February omitted). The most recent 20 years are shown; the year with "
                    "the lowest daily anomaly is red and the most recent year is orange."
                ),
            )
        )
    if will_sia_path:
        gallery_figures.append(
            GalleryFigure(
                Path(will_sia_path),
                "Daily Southern Hemisphere SIA Anomalies",
                caption=(
                    "Daily NSIDC G02202 V6 SIA anomalies relative to the 1979–2018 40-year calendar-day "
                    "climatology (29 February omitted). The most recent 20 years are shown; the year with "
                    "the lowest daily anomaly is red and the most recent year is orange."
                ),
            )
        )
    if nsidc_sic_path:
        y, m, _ = _actual_ym(latest_map_sic(), args.year, args.month)
        gallery_figures.append(
            GalleryFigure(
                Path(nsidc_sic_path),
                f"NSIDC SH SIC anomaly — {y:04d}-{m:02d}",
                caption=(
                    "Monthly-mean NSIDC G02202 V6 SIC anomaly relative to the 1979–2008 climatology. "
                    "Positive colours indicate greater-than-climatological concentration and negative colours "
                    "less ice. The black contour is the selected month's 15% SIC edge; the magenta contour is "
                    "the climatological 15% SIC edge for the same calendar month."
                ),
                extra_markdown=_history_table(
                    nsidc_history, anchor_year=y, anchor_month=m, prefix="NSIDC_SH_sic_anomaly"
                ),
            )
        )
    if bremen_sic_path:
        name = Path(bremen_sic_path).stem
        stamp = name.rsplit("_", 1)[-1]
        gallery_figures.append(
            GalleryFigure(
                Path(bremen_sic_path),
                f"University of Bremen AMSR2 SH SIC and SIE — {stamp[:4]}-{stamp[4:]}",
                caption=(
                    "Monthly-mean University of Bremen ASI-AMSR2 SIC at 6.25 km. The black contour is the "
                    "NSIDC G02202 V6 15% SIC edge and the solid orange contour is the Bremen 15% edge. "
                    "This independent, higher-resolution AMSR2 retrieval is retained alongside NSIDC to expose "
                    "edge sensitivity to sensor, retrieval method and spatial resolution rather than relying on "
                    "a single sea-ice product."
                ),
                extra_markdown=_history_table(
                    bremen_history,
                    anchor_year=int(stamp[:4]),
                    anchor_month=int(stamp[4:]),
                    prefix="BREMEN_AMSR2_SH_sic_SIE",
                ),
            )
        )
    if esa_sit_path:
        name = Path(esa_sit_path).stem
        stamp = name.rsplit("_", 1)[-1]
        gallery_figures.append(
            GalleryFigure(
                Path(esa_sit_path),
                f"ESA CCI L3C SH monthly SIT — {stamp[:4]}-{stamp[4:]}",
                caption=(
                    "Latest locally available ESA CCI v4.0 L3C monthly sea-ice thickness, averaging available "
                    "sensor fields on their common grid where more than one sensor contributes. The black contour "
                    "is the matching-month NSIDC 15% SIC edge."
                ),
                extra_markdown=_history_table(
                    esa_history,
                    anchor_year=int(stamp[:4]),
                    anchor_month=int(stamp[4:]),
                    prefix="ESA_CCI_L3C_SH_sit",
                ),
            )
        )
    if oisst_path:
        name = Path(oisst_path).stem
        stamp = name.rsplit("_", 1)[-1]
        gallery_figures.append(
            GalleryFigure(
                Path(oisst_path),
                f"OISST global SST anomaly and observed SIE — {stamp[:4]}-{stamp[4:]}",
                caption=(
                    "Floes forms the monthly SST anomaly from NOAA OISST v2.1 relative to the 1979–2008 monthly "
                    "climatology. OISST blends bias-adjusted satellite SST with ships, buoys and Argo on a 0.25° "
                    "daily grid and fills gaps by optimum interpolation; in the marginal ice zone, sea-ice "
                    "concentration supplies proxy SST where direct observations are sparse. Black is the NSIDC "
                    "15% SIC edge and dashed orange is Bremen. "
                    "[NOAA OISST methodology](https://www.ncei.noaa.gov/products/optimum-interpolation-sst)."
                ),
            )
        )
    if era5_path:
        name = Path(era5_path).stem
        stamp = name.rsplit("_", 1)[-1]
        gallery_figures.append(
            GalleryFigure(
                Path(era5_path),
                f"ERA5 wind speed, MSLP and observed SIE — {stamp[:4]}-{stamp[4:]}",
                caption=(
                    "Monthly-mean ERA5 10 m wind speed is calculated from the u10 and v10 components and plotted "
                    "from 0–30 m s⁻¹; mean sea-level pressure is overlaid as hPa contours. Black is the NSIDC 15% "
                    "SIC edge and dashed orange is the Bremen edge, providing atmospheric context for the observed "
                    "sea-ice state."
                ),
                extra_markdown=_history_table(
                    era5_history,
                    anchor_year=int(stamp[:4]),
                    anchor_month=int(stamp[4:]),
                    prefix="ERA5_wind_SIE_SH",
                ),
            )
        )
    if will_sie_max_path:
        gallery_figures.append(
            GalleryFigure(
                Path(will_sie_max_path),
                "NSIDC SIEmax vs day-of-max",
                caption=(
                    "Annual Southern Hemisphere SIE maxima are derived from daily NSIDC G02202 V6 SIE after a "
                    "centred five-day running mean over August–October. Red marks the year with the lowest annual "
                    "maximum; orange marks the latest year with an available maximum."
                ),
            )
        )
    if will_hemisphere_paths:
        monthly_path = Path(will_hemisphere_paths[1])
        gallery_figures.append(
            GalleryFigure(
                monthly_path,
                "NSIDC Arctic vs Antarctic monthly anomalies",
                description=(
                    "The left panel shows the combined Arctic and Antarctic monthly SIE anomaly: values below zero "
                    "mean global sea-ice extent was below its calendar-month climatology. In the right panel, each "
                    "point is one month; the lower-left quadrant means both hemispheres were below average, while "
                    "the opposite-sign quadrants show compensation between hemispheres. Black denotes months before "
                    f"{args.comparison_split_year}; red denotes {args.comparison_split_year} onward."
                ),
                caption=(
                    f"Constructed from separate Arctic and Antarctic calendar-month anomalies relative to the "
                    f"{args.will_clim_start}–{args.will_clim_end} NSIDC climatology; the hemispheric anomalies are "
                    "summed for the global series."
                ),
            )
        )
    gallery = write_gallery(
        fig_dir=cfg.figure_root,
        md_path=cfg.markdown_gallery,
        figures=gallery_figures,
    )
    manifest_path = cfg.figure_root / f"floes_manifest_{args.year:04d}{args.month:02d}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nWrote gallery : {gallery}")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
