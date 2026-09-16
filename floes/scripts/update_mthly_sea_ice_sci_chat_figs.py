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
from floes.observations.era5 import ERA5Reader  # noqa: E402
from floes.observations.nsidc import NSIDCReader  # noqa: E402
from floes.observations.ocean import OceanReader  # noqa: E402
from floes.observations.oisst import OISSTReader  # noqa: E402
from floes.observations.sea_ice import annual_sie_maximum  # noqa: E402
from floes.plotting.gallery import write_gallery  # noqa: E402
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
    p.add_argument("--download-missing", action="store_true", help="Reserved flag for future downloader orchestration.")
    p.add_argument("--strict", action="store_true", help="Fail on first missing optional product.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    cfg = default_config(
        project=args.project,
        user=args.user,
        gadi_base=args.gadi_base,
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
    print(f"ERA5 root      : {cfg.era5_root}")
    print(f"NSIDC daily    : {args.nsidc_daily_base}")
    print(f"Figure dir     : {cfg.figure_root}")
    print(f"Gallery        : {cfg.markdown_gallery}")

    if args.dry_run:
        print("Dry run only; no figures generated.")
        write_gallery(fig_dir=cfg.figure_root, md_path=cfg.markdown_gallery)
        return 0

    keep_going = not args.strict
    plotter = MonthlySeaIceChatPlotter(cfg)
    nsidc = NSIDCReader(cfg, hemisphere="SH", daily_base=args.nsidc_daily_base)
    monthly_totals: dict[str, object] = {}

    def total_for(hemisphere: str):
        hemisphere = hemisphere.upper()
        if hemisphere not in monthly_totals:
            print(f"Computing NSIDC {hemisphere} monthly total SIA/SIE ...", flush=True)
            monthly_totals[hemisphere] = NSIDCReader(cfg, hemisphere=hemisphere).total_sia_sie().compute()
        return monthly_totals[hemisphere]

    def nsidc_sic_map():
        ds = nsidc.sic_month_and_climatology(year=args.year, month=args.month, fallback_latest=True)
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

    _run_step("NSIDC SIC anomaly map", nsidc_sic_map, keep_going=keep_going, manifest=manifest, verbose=args.verbose)
    _run_step(
        "NSIDC total SIA/SIE time series", nsidc_sia_ts, keep_going=keep_going, manifest=manifest, verbose=args.verbose
    )

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
            )

        def will_sia_standardised_anomaly():
            ds = total_for("SH")
            return diagnostics.plot_monthly_anomaly_timeseries(
                ds["SIA"],
                output=cfg.figure_root / "NSIDC_SIA_cdr_monthly_tplot_standardised.png",
                standardised=True,
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
            maxima = annual_sie_maximum(daily["SIE"])
            maxima.to_netcdf(cfg.figure_root / "NSIDC_SH_SIE_annual_maximum.nc")
            highlight = tuple(year for year in (args.year - 1, args.year) if year >= 1979)
            return diagnostics.plot_sie_maximum_vs_day(
                maxima,
                output=cfg.figure_root / "NSIDC_SIEmax_vs_day-of-max.png",
                highlight_years=highlight,
            )

        _run_step(
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
        _run_step(
            "Will: Arctic-Antarctic SIE comparison",
            will_hemisphere_comparison,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )
        _run_step(
            "Will: SH monthly SIE anomalies by year",
            will_sie_anomalies_by_year,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )
        _run_step(
            "Will: SH SIE maximum versus date",
            will_sie_maximum,
            keep_going=keep_going,
            manifest=manifest,
            verbose=args.verbose,
        )

    def oisst_map():
        da = OISSTReader(cfg).anomaly_field(year=args.year, month=args.month, fallback_latest=True)
        y, m, exact = _actual_ym(da, args.year, args.month)
        if not exact:
            print(f"Using latest available OISST month {y:04d}-{m:02d} for requested {args.year:04d}-{args.month:02d}.")
        out = cfg.figure_root / f"OISST_global_sst_anomaly_{y:04d}{m:02d}.png"
        suffix = "" if exact else f" (latest available; requested {args.year:04d}-{args.month:02d})"
        return plotter.plot_gridded_anomaly(
            da, output=out, title=f"OISST SST anomaly, {y:04d}-{m:02d}{suffix}", limit=3.0, units_label="degC"
        )

    def era5_wind_map():
        da = ERA5Reader(cfg).wind_speed_month(year=args.year, month=args.month, fallback_latest=True)
        y, m, exact = _actual_ym(da, args.year, args.month)
        if not exact:
            print(
                f"Using latest available ERA5 wind month {y:04d}-{m:02d} "
                f"for requested {args.year:04d}-{args.month:02d}."
            )
        out = cfg.figure_root / f"ERA5_wind_SIE_SH_{y:04d}{m:02d}.png"
        suffix = "" if exact else f" (latest available; requested {args.year:04d}-{args.month:02d})"
        source = da.attrs.get("source", "ERA5")
        return plotter.plot_gridded_anomaly(
            da,
            output=out,
            title=f"{source} wind speed, {y:04d}-{m:02d}{suffix}",
            cpt="turbo",
            limit=20.0,
            units_label="m s-1",
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

    _run_step("OISST SST anomaly map", oisst_map, keep_going=True, manifest=manifest, verbose=args.verbose)
    _run_step("ERA5 wind map", era5_wind_map, keep_going=True, manifest=manifest, verbose=args.verbose)
    _run_step(
        "ORAS5 depth-time diagnostic", oras_hovmoller_scaffold, keep_going=True, manifest=manifest, verbose=args.verbose
    )
    _run_step(
        "EN4 depth-time diagnostic", en4_hovmoller_scaffold, keep_going=True, manifest=manifest, verbose=args.verbose
    )

    gallery = write_gallery(fig_dir=cfg.figure_root, md_path=cfg.markdown_gallery)
    manifest_path = cfg.figure_root / f"floes_manifest_{args.year:04d}{args.month:02d}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nWrote gallery : {gallery}")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
