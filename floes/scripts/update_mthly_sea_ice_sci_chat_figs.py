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
    return (
        int(attrs.get("selected_year", fallback_year)),
        int(attrs.get("selected_month", fallback_month)),
        bool(attrs.get("exact_requested_month", True)),
    )


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
    p.add_argument(
        "--gadi-base",
        type=Path,
        default=Path("/g/data/gv90/wrh581"),
        help="Base directory containing known observational resources.",
    )
    p.add_argument(
        "--era5-root",
        type=Path,
        default=Path("/g/data/rt52"),
        help="Root containing the official era5/ and near-real-time era5t/ collections.",
    )
    p.add_argument(
        "--seaice-root",
        type=Path,
        default=Path("/g/data/gv90/da1339/SeaIce"),
        help="Local archive for NSIDC, University of Bremen and ESA CCI sea-ice products.",
    )
    p.add_argument("--fig-dir", type=Path, default=None, help="Figure output directory.")
    p.add_argument("--docs-dir", type=Path, default=None, help="Documentation/gallery output directory.")
    p.add_argument("--year", type=int, default=default_year)
    p.add_argument("--month", type=int, default=default_month)
    p.add_argument("--clim-start", type=int, default=1979)
    p.add_argument("--clim-end", type=int, default=2008)
    p.add_argument("--will-clim-start", type=int, default=1979, help="Start year for legacy Will Hobbs diagnostics.")
    p.add_argument("--will-clim-end", type=int, default=2018, help="End year for legacy Will Hobbs diagnostics.")
    p.add_argument(
        "--comparison-split-year",
        type=int,
        default=2005,
        help="Year separating black/red points in hemispheric comparisons.",
    )
    p.add_argument(
        "--nsidc-daily-base",
        type=Path,
        default=Path("/g/data/jk72/wrh581"),
        help="Base containing NSIDC/SIE_daily pre-integrated daily files.",
    )
    p.add_argument("--skip-will-suite", action="store_true", help="Skip the legacy NSIDC diagnostic reproductions.")
    p.add_argument("--strict", action="store_true", help="Fail on first missing optional product.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    cfg = default_config(
        project=args.project,
        user=args.user,
        gadi_base=args.gadi_base,
        seaice_root=args.seaice_root,
        era5_root=args.era5_root,
        output_root=args.fig_dir,
        docs_root=args.docs_dir,
        climatology_start=args.clim_start,
        climatology_end=args.clim_end,
    )
    cfg.figure_root.mkdir(parents=True, exist_ok=True)
    cfg.markdown_gallery.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "requested_year": args.year,
        "requested_month": args.month,
        "gadi_base": str(cfg.gadi_base),
        "seaice_root": str(cfg.seaice_root),
        "era5_root": str(cfg.era5_root),
        "nsidc_daily_base": str(args.nsidc_daily_base),
        "figure_root": str(cfg.figure_root),
        "gallery": str(cfg.markdown_gallery),
        "steps": {},
    }

    print("floes monthly science-chat update")
    print(f"Requested month: {args.year:04d}-{args.month:02d}")
    print(
        "Note           : if that month is unavailable, map products fall back to latest available <= requested month."
    )
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
    map_sic_cache: dict[str, object] = {}
    bremen_cache: dict[tuple[int, int], object] = {}

    def total_for(hemisphere: str):
        hemisphere = hemisphere.upper()
        if hemisphere not in monthly_totals:
            print(f"Computing NSIDC {hemisphere} monthly total SIA/SIE ...", flush=True)
            monthly_totals[hemisphere] = NSIDCReader(cfg, hemisphere=hemisphere).total_sia_sie().compute()
        return monthly_totals[hemisphere]

    def latest_map_sic():
        if "dataset" not in map_sic_cache:
            map_sic_cache["dataset"] = nsidc.sic_month_and_climatology(
                year=args.year,
                month=args.month,
                fallback_latest=True,
            ).compute()
        return map_sic_cache["dataset"]

    def ice_edge_for(year: int, month: int):
        latest = latest_map_sic()
        latest_year, latest_month, _ = _actual_ym(latest, args.year, args.month)
        if (year, month) == (latest_year, latest_month):
            return latest["sic"]
        return nsidc.sic_month_and_climatology(
            year=year,
            month=month,
            fallback_latest=False,
        )["sic"].compute()

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

    def nsidc_sic_map():
        ds = latest_map_sic()
        y, m, exact = _actual_ym(ds, args.year, args.month)
        if not exact:
            print(f"Using latest available NSIDC month {y:04d}-{m:02d} for requested {args.year:04d}-{args.month:02d}.")
        out = cfg.figure_root / f"NSIDC_SH_sic_anomaly_{y:04d}{m:02d}.png"
        return plotter.plot_sic_anomaly_map(ds, year=args.year, month=args.month, output=out, stride=2)

    def nsidc_sia_ts():
        ds = total_for("SH")
        nc = cfg.figure_root / "NSIDC_SH_total_SIA_SIE_monthly.nc"
        ds.to_netcdf(nc)
        out = cfg.figure_root / "NSIDC_SH_total_SIA_SIE_monthly.png"
        return plotter.plot_total_sia_sie(ds, output=out)

    def bremen_sic_map():
        da = bremen.month(year=args.year, month=args.month, fallback_latest=True).compute()
        y, m, exact = _actual_ym(da, args.year, args.month)
        if not exact:
            print(
                f"Using latest available Bremen SIC month {y:04d}-{m:02d} "
                f"for requested {args.year:04d}-{args.month:02d}."
            )
        out = cfg.figure_root / f"BREMEN_AMSR2_SH_sic_SIE_{y:04d}{m:02d}.png"
        return plotter.plot_gridded_anomaly(
            da,
            output=out,
            title=f"{y:04d}-{m:02d}",
            cpt="cmocean/ice",
            value_range=(0.0, 1.0),
            colorbar_label="sea-ice concentration",
            colorbar_unit="fraction",
            ice_edges=[
                (ice_edge_for(y, m), "1.0p,black"),
                (da, "1.0p,orange,-"),
            ],
            stride=2,
        )

    def bremen_processed_products():
        processed = bremen.root / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        monthly_path = processed / "BREMEN_AMSR2_SH_SIC_monthly.nc"
        totals_path = processed / "BREMEN_AMSR2_SH_SIA_SIE_daily.nc"
        sic = bremen.sic()
        sic.resample(time="MS").mean(skipna=True).to_dataset(name="sic").to_netcdf(monthly_path)
        bremen.total_sia_sie().to_netcdf(totals_path)
        return f"{monthly_path}; {totals_path}"

    def esa_cci_sit_map():
        da = esa_cci.month(year=args.year, month=args.month, fallback_latest=True).compute()
        y, m, exact = _actual_ym(da, args.year, args.month)
        if not exact:
            print(
                f"Using latest available ESA CCI L3C SIT month {y:04d}-{m:02d} "
                f"for requested {args.year:04d}-{args.month:02d}."
            )
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
            stride=1,
        )

    nsidc_sic_path = _run_step(
        "NSIDC SIC anomaly map", nsidc_sic_map, keep_going=keep_going, manifest=manifest, verbose=args.verbose
    )
    _run_step(
        "NSIDC total SIA/SIE time series", nsidc_sia_ts, keep_going=keep_going, manifest=manifest, verbose=args.verbose
    )
    _run_step(
        "Process University of Bremen SIC/SIA/SIE",
        bremen_processed_products,
        keep_going=True,
        manifest=manifest,
        verbose=args.verbose,
    )
    bremen_sic_path = _run_step(
        "University of Bremen AMSR2 SIC/SIE map",
        bremen_sic_map,
        keep_going=True,
        manifest=manifest,
        verbose=args.verbose,
    )
    esa_sit_path = _run_step(
        "ESA CCI L3C SIT map",
        esa_cci_sit_map,
        keep_going=True,
        manifest=manifest,
        verbose=args.verbose,
    )

    will_sia_path = None
    will_sie_by_year_path = None
    will_sie_max_path = None
    will_hemisphere_paths = None

    if not args.skip_will_suite:
        diagnostics = NSIDCDiagnosticPlotter(
            climatology_start=args.will_clim_start,
            climatology_end=args.will_clim_end,
            comparison_split_year=args.comparison_split_year,
        )

        def will_sia_anomaly():
            ds = total_for("SH")
            return diagnostics.plot_monthly_anomaly_timeseries(
                ds["SIA"],
                output=cfg.figure_root / "NSIDC_SIA_cdr_monthly_tplot_absolute.png",
                highlight_year=args.year,
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
            ds = total_for("SH")
            return diagnostics.plot_monthly_anomalies_by_year(
                ds["SIE"],
                output=cfg.figure_root / "NSIDC_SIE_cdr_monthly_anoms_byyear.png",
                highlight_year=args.year,
            )

        def will_sie_maximum():
            daily = nsidc.daily_total_sia_sie()
            daily.to_netcdf(cfg.figure_root / "NSIDC_SH_total_SIA_SIE_daily.nc")
            maxima = annual_sie_maximum(daily["SIE"])
            maxima.to_netcdf(cfg.figure_root / "NSIDC_SH_SIE_annual_maximum.nc")
            return diagnostics.plot_sie_maximum_vs_day(
                maxima,
                output=cfg.figure_root / "NSIDC_SIEmax_vs_day-of-max.png",
                current_year=args.year,
            )

        will_sia_path = _run_step(
            "Will: SH monthly SIA anomaly",
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
            "Will: SH monthly SIE anomalies by year",
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

    def era5_wind_map():
        sic = latest_map_sic()
        target_year, target_month, _ = _actual_ym(sic, args.year, args.month)
        fields = ERA5Reader(cfg).wind_mslp_month(
            year=target_year,
            month=target_month,
            fallback_latest=True,
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
            value_range=(0.0, 40.0),
            colorbar_label="wind speed",
            colorbar_unit="m/s",
            ice_edges=comparison_edges(y, m),
            contour=fields["mslp"],
            contour_interval=4.0,
            contour_annotation=8.0,
            contour_pen="0.45p,gray40",
        )

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

    oisst_path = _run_step(
        "OISST SST anomaly map", oisst_map, keep_going=True, manifest=manifest, verbose=args.verbose
    )
    era5_path = _run_step(
        "ERA5 wind map", era5_wind_map, keep_going=True, manifest=manifest, verbose=args.verbose
    )
    _run_step(
        "ORAS5 depth-time diagnostic", oras_hovmoller_scaffold, keep_going=True, manifest=manifest, verbose=args.verbose
    )
    _run_step(
        "EN4 depth-time diagnostic", en4_hovmoller_scaffold, keep_going=True, manifest=manifest, verbose=args.verbose
    )

    gallery_figures: list[GalleryFigure] = []
    if will_sie_by_year_path:
        gallery_figures.append(
            GalleryFigure(Path(will_sie_by_year_path), "NSIDC SIE cdr monthly anoms byyear")
        )
    if will_sia_path:
        gallery_figures.append(
            GalleryFigure(Path(will_sia_path), "NSIDC SIA cdr monthly tplot absolute")
        )
    if nsidc_sic_path:
        y, m, _ = _actual_ym(latest_map_sic(), args.year, args.month)
        gallery_figures.append(
            GalleryFigure(Path(nsidc_sic_path), f"NSIDC SH sic anomaly — {y:04d}-{m:02d}")
        )
    if bremen_sic_path:
        name = Path(bremen_sic_path).stem
        stamp = name.rsplit("_", 1)[-1]
        gallery_figures.append(
            GalleryFigure(
                Path(bremen_sic_path),
                f"University of Bremen AMSR2 SH SIC and SIE — {stamp[:4]}-{stamp[4:]}",
                caption=(
                    "Monthly-mean ASI-AMSR2 SIC; black edge is NSIDC and dashed orange edge is Bremen, "
                    "both at 15% SIC."
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
                caption="Monthly gridded L3C sea-ice thickness; black line is the matching-month NSIDC 15% SIC edge.",
            )
        )
    if oisst_path:
        name = Path(oisst_path).stem
        stamp = name.rsplit("_", 1)[-1]
        gallery_figures.append(
            GalleryFigure(
                Path(oisst_path),
                f"OISST global SST anomaly and observed SIE — {stamp[:4]}-{stamp[4:]}",
                caption="Black edge is NSIDC and dashed orange edge is University of Bremen AMSR2, both at 15% SIC.",
            )
        )
    if era5_path:
        name = Path(era5_path).stem
        stamp = name.rsplit("_", 1)[-1]
        gallery_figures.append(
            GalleryFigure(
                Path(era5_path),
                f"ERA5 wind speed, MSLP and observed SIE — {stamp[:4]}-{stamp[4:]}",
                caption="Black edge is NSIDC and dashed orange edge is University of Bremen AMSR2, both at 15% SIC.",
            )
        )
    if will_sie_max_path:
        gallery_figures.append(GalleryFigure(Path(will_sie_max_path), "NSIDC SIEmax vs day-of-max"))
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
