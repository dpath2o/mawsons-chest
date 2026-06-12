#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

THIS = Path(__file__).resolve()
FLOES_ROOT = THIS.parents[1]
PARENT = FLOES_ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from floes.config import default_config, previous_complete_month  # noqa: E402
from floes.observations.nsidc import NSIDCReader  # noqa: E402
from floes.observations.oisst import OISSTReader  # noqa: E402
from floes.observations.era5 import ERA5Reader  # noqa: E402
from floes.observations.ocean import OceanReader  # noqa: E402
from floes.plotting.monthly import MonthlySeaIceChatPlotter  # noqa: E402
from floes.plotting.gallery import write_gallery  # noqa: E402


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
    p.add_argument("--gadi-base", type=Path, default=Path("/g/data/gv90/wrh581"), help="Base directory containing known observational resources.")
    p.add_argument("--fig-dir", type=Path, default=None, help="Figure output directory.")
    p.add_argument("--docs-dir", type=Path, default=None, help="Documentation/gallery output directory.")
    p.add_argument("--year", type=int, default=default_year)
    p.add_argument("--month", type=int, default=default_month)
    p.add_argument("--clim-start", type=int, default=1979)
    p.add_argument("--clim-end", type=int, default=2008)
    p.add_argument("--download-missing", action="store_true", help="Reserved flag for future downloader orchestration.")
    p.add_argument("--strict", action="store_true", help="Fail on first missing optional product.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    cfg = default_config(
        project=args.project,
        user=args.user,
        gadi_base=args.gadi_base,
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
        "figure_root": str(cfg.figure_root),
        "gallery": str(cfg.markdown_gallery),
        "steps": {},
    }

    print("floes monthly science-chat update")
    print(f"Requested month: {args.year:04d}-{args.month:02d}")
    print("Note           : if that month is unavailable, map products fall back to latest available <= requested month.")
    print(f"Gadi base      : {cfg.gadi_base}")
    print(f"Figure dir     : {cfg.figure_root}")
    print(f"Gallery        : {cfg.markdown_gallery}")

    if args.dry_run:
        print("Dry run only; no figures generated.")
        write_gallery(fig_dir=cfg.figure_root, md_path=cfg.markdown_gallery)
        return 0

    keep_going = not args.strict
    plotter = MonthlySeaIceChatPlotter(cfg)
    nsidc = NSIDCReader(cfg)

    def nsidc_sic_map():
        ds = nsidc.sic_month_and_climatology(year=args.year, month=args.month, fallback_latest=True)
        y, m, exact = _actual_ym(ds, args.year, args.month)
        if not exact:
            print(f"Using latest available NSIDC month {y:04d}-{m:02d} for requested {args.year:04d}-{args.month:02d}.")
        out = cfg.figure_root / f"NSIDC_SH_sic_anomaly_{y:04d}{m:02d}.png"
        return plotter.plot_sic_anomaly_map(ds, year=args.year, month=args.month, output=out, stride=2)

    def nsidc_sia_ts():
        ds = nsidc.total_sia_sie()
        nc = cfg.figure_root / "NSIDC_SH_total_SIA_SIE_monthly.nc"
        ds.to_netcdf(nc)
        out = cfg.figure_root / "NSIDC_SH_total_SIA_SIE_monthly.png"
        return plotter.plot_total_sia_sie(ds, output=out)

    _run_step("NSIDC SIC anomaly map", nsidc_sic_map, keep_going=keep_going, manifest=manifest, verbose=args.verbose)
    _run_step("NSIDC total SIA/SIE time series", nsidc_sia_ts, keep_going=keep_going, manifest=manifest, verbose=args.verbose)

    def oisst_map():
        da = OISSTReader(cfg).anomaly_field(year=args.year, month=args.month, fallback_latest=True)
        y, m, exact = _actual_ym(da, args.year, args.month)
        if not exact:
            print(f"Using latest available OISST month {y:04d}-{m:02d} for requested {args.year:04d}-{args.month:02d}.")
        out = cfg.figure_root / f"OISST_global_sst_anomaly_{y:04d}{m:02d}.png"
        suffix = "" if exact else f" (latest available; requested {args.year:04d}-{args.month:02d})"
        return plotter.plot_gridded_anomaly(da, output=out, title=f"OISST SST anomaly, {y:04d}-{m:02d}{suffix}", limit=3.0, units_label="degC")

    def era5_wind_map():
        da = ERA5Reader(cfg).wind_speed_month(year=args.year, month=args.month, fallback_latest=True)
        y, m, exact = _actual_ym(da, args.year, args.month)
        if not exact:
            print(f"Using latest available ERA5 wind month {y:04d}-{m:02d} for requested {args.year:04d}-{args.month:02d}.")
        out = cfg.figure_root / f"ERA5_wind_SIE_SH_{y:04d}{m:02d}.png"
        suffix = "" if exact else f" (latest available; requested {args.year:04d}-{args.month:02d})"
        return plotter.plot_gridded_anomaly(da, output=out, title=f"ERA5 wind speed, {y:04d}-{m:02d}{suffix}", cpt="turbo", limit=20.0, units_label="m s-1")

    def oras_hovmoller_scaffold():
        reader = OceanReader(cfg)
        da = reader.read(src="ORAS5", var="thetao", start_year=max(args.year - 5, 1979), end_year=args.year, latmin=-80, latmax=-45, zmin=0, zmax=1000, allow_latest=True)
        zdim = next((d for d in ("deptht", "depth", "depth_std", "lev") if d in da.dims), None)
        exclude = {"time"}
        if zdim:
            exclude.add(zdim)
        spatial_dims = [d for d in da.dims if d not in exclude]
        hov = da.mean(dim=spatial_dims, skipna=True) if spatial_dims else da
        nc = cfg.figure_root / f"ORAS5_thetao_depth_time_SH_latest.nc"
        hov.to_netcdf(nc)
        return nc

    _run_step("OISST SST anomaly map", oisst_map, keep_going=True, manifest=manifest, verbose=args.verbose)
    _run_step("ERA5 wind map", era5_wind_map, keep_going=True, manifest=manifest, verbose=args.verbose)
    _run_step("ORAS5 depth-time diagnostic", oras_hovmoller_scaffold, keep_going=True, manifest=manifest, verbose=args.verbose)

    gallery = write_gallery(fig_dir=cfg.figure_root, md_path=cfg.markdown_gallery)
    manifest_path = cfg.figure_root / f"floes_manifest_{args.year:04d}{args.month:02d}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nWrote gallery : {gallery}")
    print(f"Wrote manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
