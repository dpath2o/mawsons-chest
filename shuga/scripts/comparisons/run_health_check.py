#!/usr/bin/env python3
"""
Compare the health of a short CICE run against a pre-processed reference run.

The candidate run is the only simulation that may be processed. Its original
NetCDF history files are treated as read-only inputs and are never moved or
deleted. The reference simulation is read only: existing shuga metrics are
sliced to the candidate date range and are never reclassified or recomputed.

Because shuga does not currently persist SIE or hemispheric mean SIC as CICE
metrics, those two diagnostics are calculated transiently from the candidate
and reference CICE history stores. No reference products are written.

Outputs (per hemisphere)
------------------------
- health_<HEMI>.png       : 8-panel candidate/reference time-series overview
- timeseries_<HEMI>.csv   : aligned daily diagnostics
- summary_<HEMI>.csv      : compact comparison statistics
- sanity_checks.csv       : data-integrity / physical-range checks
- health_report.txt       : human-readable run summary

The reference comparison is diagnostic, not a model-skill pass/fail test. This
is especially important for experiments that deliberately start from zero sea
ice and are expected to recover toward a spun-up state.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shuga import ClassificationSpec, RunSpec, ShugaPaths, load_cice, load_metrics  # noqa: E402

DATE_RE = re.compile(r"^iceh\.(\d{4}-\d{2}-\d{2})\.nc$")
CORE_SI = ("SIA", "SIT", "SIS")
CORE_FI = ("FIA", "FIT", "FIS")
PLOT_ORDER = ("SIC", "SIA", "SIE", "SIT", "SIS", "FIA", "FIT", "FIS")
PLOT_LABELS = {
    "SIC": "Mean SIC over 15% extent",
    "SIA": "Sea-ice area",
    "SIE": "Sea-ice extent",
    "SIT": "Sea-ice thickness",
    "SIS": "Sea-ice strength",
    "FIA": "Fast-ice area",
    "FIT": "Fast-ice thickness",
    "FIS": "Fast-ice strength",
}
DISPLAY_UNITS = {
    "SIC": "%",
    "SIA": "10$^6$ km$^2$",
    "SIE": "10$^6$ km$^2$",
    "SIT": "m",
    "SIS": "MPa",
    "FIA": "10$^6$ km$^2$",
    "FIT": "m",
    "FIS": "MPa",
}


@dataclass(frozen=True)
class SourceFileState:
    size: int
    mtime_ns: int


@dataclass
class Check:
    hemisphere: str
    check: str
    status: str
    detail: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Assess a candidate CICE run against an existing shuga reference simulation.")
    p.add_argument("--run-name", required=True, help="Candidate simulation name, e.g. frcg-exp01.")
    p.add_argument("--history-root", default=None,
                   help="Directory containing candidate iceh.YYYY-MM-DD.nc files. Default: /g/data/PROJECT/USER/cice-dirs/runs/RUN_NAME/history")
    p.add_argument("--reference-sim", default="Cs-high")
    p.add_argument("--reference-root", default=None,
                   help="Optional explicit reference simulation root. Default: AFIM_OUTPUT_ROOT/REFERENCE_SIM. This location is always read-only.")
    p.add_argument("--afim-output-root", default=None)
    p.add_argument("--static-store", default=None)
    p.add_argument("--project", default="gv90")
    p.add_argument("--user", default="da1339")
    p.add_argument("--start-date", default=None, help="Optional YYYY-MM-DD; otherwise inferred from filenames.")
    p.add_argument("--end-date", default=None, help="Optional YYYY-MM-DD; otherwise inferred from filenames.")
    p.add_argument("--hemispheres", default="SH,NH", help="Comma-separated; default SH,NH.")
    p.add_argument("--fi-method", default="binary-days")
    p.add_argument("--grid-type", default="Tc")
    p.add_argument("--ispd-thresh", type=float, default=5.0e-4)
    p.add_argument("--bin-window", type=int, default=11)
    p.add_argument("--bin-min-days", type=int, default=9)
    p.add_argument("--roll-window", type=int, default=15)
    p.add_argument("--ice-threshold", type=float, default=0.15)
    p.add_argument("--final-window", type=int, default=14, help="Days used for final-window summary statistics.")
    p.add_argument("--chunks-time", type=int, default=31)
    p.add_argument("--netcdf-engine", default="scipy")
    p.add_argument("--outdir", default=None)
    p.add_argument("--skip-candidate-processing", action="store_true",
                   help="Do not run candidate NetCDF conversion/classification/metrics; use existing derived stores.")
    p.add_argument("--overwrite-candidate-history", action="store_true",
                   help="Allow candidate NetCDF->Zarr history groups to be refreshed. Raw NetCDF files remain untouched.")
    p.add_argument("--overwrite-candidate-classification", action="store_true",
                   help="Overwrite candidate FI classification outputs for the requested period.")
    p.add_argument("--overwrite-candidate-metrics", action="store_true",
                   help="Rebuild candidate requested metrics stores. Never applies to the reference simulation.")
    return p.parse_args()


def canonical_hemisphere(value: str) -> str:
    token = value.strip().upper()
    mapping = {"S": "SH", "SH": "SH", "SOUTH": "SH", "N": "NH", "NH": "NH", "NORTH": "NH"}
    if token not in mapping:
        raise ValueError(f"Unsupported hemisphere {value!r}; use SH/NH.")
    return mapping[token]


def resolve_roots(args: argparse.Namespace) -> tuple[Path, Path, Path, Path | None]:
    afim_root = Path(args.afim_output_root).expanduser() if args.afim_output_root else Path(f"/g/data/{args.project}/{args.user}/afim_output")
    history_root = Path(args.history_root).expanduser() if args.history_root else Path(f"/g/data/{args.project}/{args.user}/cice-dirs/runs/{args.run_name}/history")
    reference_root = Path(args.reference_root).expanduser() if args.reference_root else afim_root / args.reference_sim
    static_store = Path(args.static_store).expanduser() if args.static_store else None
    return afim_root, history_root, reference_root, static_store


def discover_history_files(history_root: Path, start_date: str | None, end_date: str | None):
    if not history_root.exists():
        raise FileNotFoundError(f"Candidate history root does not exist: {history_root}")
    dated: list[tuple[pd.Timestamp, Path]] = []
    for path in sorted(history_root.glob("iceh.*.nc")):
        match = DATE_RE.match(path.name)
        if match:
            dated.append((pd.Timestamp(match.group(1)), path))
    if not dated:
        raise FileNotFoundError(f"No iceh.YYYY-MM-DD.nc files found directly under candidate history root: {history_root}")
    dates = pd.DatetimeIndex([d for d, _ in dated])
    if dates.duplicated().any():
        dup = dates[dates.duplicated()].strftime("%Y-%m-%d").tolist()
        raise ValueError(f"Duplicate candidate history dates found: {dup}")
    use_start = pd.Timestamp(start_date) if start_date else dates.min()
    use_end = pd.Timestamp(end_date) if end_date else dates.max()
    if use_end < use_start:
        raise ValueError(f"Requested date range is reversed: {use_start.date()} -> {use_end.date()}")
    if use_start < dates.min() or use_end > dates.max():
        raise ValueError(f"Requested window {use_start.date()} -> {use_end.date()} exceeds available candidate files {dates.min().date()} -> {dates.max().date()}.")
    selected = [(d, p) for d, p in dated if use_start <= d <= use_end]
    selected_dates = pd.DatetimeIndex([d for d, _ in selected])
    expected = pd.date_range(use_start, use_end, freq="D")
    missing = expected.difference(selected_dates)
    return selected, use_start, use_end, missing


def snapshot_source(files: list[Path]) -> dict[Path, SourceFileState]:
    out = {}
    for path in files:
        st = path.stat()
        out[path] = SourceFileState(size=st.st_size, mtime_ns=st.st_mtime_ns)
    return out


def verify_source_unchanged(snapshot: dict[Path, SourceFileState]) -> None:
    changed: list[str] = []
    for path, before in snapshot.items():
        if not path.exists():
            changed.append(f"MISSING: {path}")
            continue
        st = path.stat()
        if st.st_size != before.size or st.st_mtime_ns != before.mtime_ns:
            changed.append(f"MODIFIED: {path}")
    if changed:
        raise RuntimeError("Candidate source NetCDF files changed during health processing.\n" + "\n".join(changed[:20]))


def run_command(cmd: list[str]) -> None:
    print("\n+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def process_candidate(args: argparse.Namespace, history_root: Path, afim_root: Path, static_store: Path | None,
                      start: pd.Timestamp, end: pd.Timestamp, hemispheres: list[str]) -> None:
    classify_py = REPO_ROOT / "shuga" / "scripts" / "classification" / "classify.py"
    metrics_py = REPO_ROOT / "shuga" / "scripts" / "metrics" / "metrics.py"
    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    for idx, hemi in enumerate(hemispheres):
        cmd = [sys.executable, str(classify_py), "--sim-name", args.run_name, "--start-date", start_s, "--end-date", end_s,
               "--hemisphere", hemi, "--project", args.project, "--user", args.user, "--ice-type", "FI",
               "--grid-type", args.grid_type, "--ispd-thresh", f"{args.ispd_thresh:.12g}", "--methods", args.fi_method,
               "--bin-window", str(args.bin_window), "--bin-min-days", str(args.bin_min_days), "--roll-window", str(args.roll_window),
               "--daily-root", str(history_root), "--afim-output-root", str(afim_root), "--chunks-time", str(args.chunks_time),
               "--netcdf-engine", args.netcdf_engine]
        if static_store is not None:
            cmd += ["--static-store", str(static_store)]
        if idx > 0:
            cmd.append("--skip-history-conversion")
        elif args.overwrite_candidate_history:
            cmd.append("--overwrite-history")
        if args.overwrite_candidate_classification:
            cmd.append("--overwrite")
        run_command(cmd)
    requested = ",".join((*CORE_SI, *CORE_FI))
    for hemi in hemispheres:
        cmd = [sys.executable, str(metrics_py), "--sim-name", args.run_name, "--start-date", start_s, "--end-date", end_s,
               "--hemisphere", hemi, "--project", args.project, "--user", args.user, "--ice-type", "FI",
               "--grid-type", args.grid_type, "--ispd-thresh", f"{args.ispd_thresh:.12g}", "--methods", args.fi_method,
               "--bin-window", str(args.bin_window), "--bin-min-days", str(args.bin_min_days), "--roll-window", str(args.roll_window),
               "--metric-names", requested, "--afim-output-root", str(afim_root)]
        if static_store is not None:
            cmd += ["--static-store", str(static_store)]
        if args.overwrite_candidate_metrics:
            cmd.append("--overwrite")
        run_command(cmd)


def make_context(*, sim_name: str, hemisphere: str, start: str, end: str, project: str, user: str,
                 afim_root: Path, static_store: Path | None, args: argparse.Namespace, ice_type: str):
    run_cfg = RunSpec(sim_name=sim_name, start_date=start, end_date=end, hemisphere=hemisphere,
                      project=project, user=user, iceh_frequency="daily")
    cls_cfg = ClassificationSpec(ice_type=ice_type, grid_type=args.grid_type, ispd_thresh=args.ispd_thresh,
                                 methods=(args.fi_method,), bin_window=args.bin_window,
                                 bin_min_days=args.bin_min_days, roll_window=args.roll_window)
    pth_cfg = ShugaPaths(run_cfg=run_cfg, cls_cfg=cls_cfg, afim_output_root=afim_root,
                         archive_root=afim_root, static_store=static_store)
    return run_cfg, cls_cfg, pth_cfg


def open_metric_group(*, sim_name: str, hemisphere: str, start: str, end: str, afim_root: Path,
                      static_store: Path | None, args: argparse.Namespace, ice_type: str, variables: tuple[str, ...]) -> xr.Dataset:
    run_cfg, cls_cfg, pth_cfg = make_context(sim_name=sim_name, hemisphere=hemisphere, start=start, end=end,
                                             project=args.project, user=args.user, afim_root=afim_root,
                                             static_store=static_store, args=args, ice_type=ice_type)
    classification = args.fi_method if ice_type == "FI" else "raw"
    return load_metrics(run_cfg=run_cfg, cls_cfg=cls_cfg, pth_cfg=pth_cfg, classification=classification,
                        dt0_str=start, dtN_str=end, variables=list(variables), hemisphere=hemisphere,
                        chunks={"time": args.chunks_time})


def open_cice_for_health(*, sim_name: str, sim_root: Path, hemisphere: str, start: str, end: str,
                         afim_root: Path, static_store: Path | None, args: argparse.Namespace,
                         variables: list[str]) -> xr.Dataset:
    run_cfg, cls_cfg, pth_cfg = make_context(sim_name=sim_name, hemisphere=hemisphere, start=start, end=end,
                                             project=args.project, user=args.user, afim_root=afim_root,
                                             static_store=static_store, args=args, ice_type="FI")
    cice_store = sim_root / "zarr" / "iceh_daily.zarr"
    if not cice_store.exists():
        raise FileNotFoundError(f"CICE daily Zarr store not found: {cice_store}")
    return load_cice(run_cfg=run_cfg, cls_cfg=cls_cfg, pth_cfg=pth_cfg, dt0_str=start, dtN_str=end,
                     variables=variables, hemisphere=hemisphere, cice_store=cice_store,
                     static_store=static_store, chunks={"time": args.chunks_time})


def aice_fraction(aice: xr.DataArray) -> xr.DataArray:
    max_value = float(aice.max(skipna=True).compute())
    return aice / 100.0 if max_value > 1.5 else aice


def spatial_dims(da: xr.DataArray) -> tuple[str, ...]:
    dims = tuple(d for d in da.dims if d != "time")
    if not dims:
        raise ValueError(f"Could not infer spatial dimensions from {da.name!r}: {da.dims}")
    return dims


def transient_sic_sie(ds: xr.Dataset, threshold: float) -> dict[str, xr.DataArray]:
    aice = aice_fraction(ds["aice"])
    area = ds["tarea"]
    while "time" in area.dims:
        area = area.isel(time=0, drop=True)
    dims = spatial_dims(aice)
    valid = np.isfinite(aice) & np.isfinite(area) & (area > 0.0)
    extent = valid & (aice >= threshold)
    area_extent = xr.where(extent, area, 0.0).sum(dim=dims)
    sie = (area_extent / 1.0e12).rename("SIE")
    sic_num = xr.where(extent, aice * area, 0.0).sum(dim=dims)
    sic = (100.0 * sic_num / area_extent.where(area_extent > 0.0)).rename("SIC")
    sie.attrs.update(long_name=f"Sea-ice extent at aice >= {threshold:g}", units="10^6 km^2")
    sic.attrs.update(long_name=f"Area-weighted mean SIC within {threshold:g} extent", units="%")
    return {"SIC": sic, "SIE": sie}


def normalize_area_for_display(da: xr.DataArray) -> xr.DataArray:
    units = str(da.attrs.get("units", "")).lower().replace(" ", "")
    out = da
    if "10^3" in units or "10³" in units:
        out = da / 1000.0
    elif units in {"m^2", "m2", "m²"}:
        out = da / 1.0e12
    return out


def to_series(da: xr.DataArray) -> pd.Series:
    work = da.squeeze(drop=True)
    extra = [d for d in work.dims if d != "time"]
    if extra:
        raise ValueError(f"Health diagnostic {da.name!r} is not 1-D in time: {work.dims}")
    values = np.asarray(work.compute().values, dtype=float)
    index = pd.DatetimeIndex(pd.to_datetime(work.time.values)).tz_localize(None)
    return pd.Series(values, index=index, name=da.name).sort_index()


def metric_series(ds: xr.Dataset, name: str) -> pd.Series:
    if name not in ds:
        return pd.Series(dtype=float, name=name)
    da = normalize_area_for_display(ds[name]) if name in {"SIA", "FIA"} else ds[name]
    return to_series(da)


def load_health_series(*, sim_name: str, sim_root: Path, hemisphere: str, start: str, end: str,
                       afim_root: Path, static_store: Path | None, args: argparse.Namespace,
                       allow_missing_metrics: bool, checks: list[Check]) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for ice_type, names in (("SI", CORE_SI), ("FI", CORE_FI)):
        try:
            ds = open_metric_group(sim_name=sim_name, hemisphere=hemisphere, start=start, end=end,
                                   afim_root=afim_root, static_store=static_store, args=args,
                                   ice_type=ice_type, variables=names)
        except (FileNotFoundError, ValueError, KeyError) as exc:
            if not allow_missing_metrics:
                raise
            checks.append(Check(hemisphere, f"reference_{ice_type.lower()}_metrics", "WARN",
                                f"Reference metrics unavailable; leaving {','.join(names)} blank: {exc}"))
            ds = xr.Dataset()
        for name in names:
            out[name] = metric_series(ds, name)
            if name not in ds and allow_missing_metrics:
                checks.append(Check(hemisphere, f"reference_metric_{name}", "WARN",
                                    f"{name} not present in existing reference metrics store; reference was not recomputed."))
    try:
        cice = open_cice_for_health(sim_name=sim_name, sim_root=sim_root, hemisphere=hemisphere,
                                    start=start, end=end, afim_root=afim_root, static_store=static_store,
                                    args=args, variables=["aice", "tarea"])
        for name, da in transient_sic_sie(cice, args.ice_threshold).items():
            out[name] = to_series(da)
    except Exception as exc:
        if not allow_missing_metrics:
            raise
        checks.append(Check(hemisphere, "reference_sic_sie", "WARN", f"Could not derive reference SIC/SIE: {exc}"))
        out["SIC"] = pd.Series(dtype=float, name="SIC")
        out["SIE"] = pd.Series(dtype=float, name="SIE")
    return out


def candidate_physical_checks(*, sim_root: Path, hemisphere: str, start: str, end: str,
                              afim_root: Path, static_store: Path | None, args: argparse.Namespace) -> list[Check]:
    checks: list[Check] = []
    ds = open_cice_for_health(sim_name=args.run_name, sim_root=sim_root, hemisphere=hemisphere,
                              start=start, end=end, afim_root=afim_root, static_store=static_store,
                              args=args, variables=["aice", "hi", "strength", "tarea"])
    aice = aice_fraction(ds["aice"])
    amin = float(aice.min(skipna=True).compute())
    amax = float(aice.max(skipna=True).compute())
    checks.append(Check(hemisphere, "aice_range", "PASS" if amin >= -1e-6 and amax <= 1.0 + 1e-6 else "FAIL",
                        f"min={amin:.6g}, max={amax:.6g}; expected approximately [0,1]."))
    for name in ("hi", "strength"):
        vmin = float(ds[name].min(skipna=True).compute())
        vmax = float(ds[name].max(skipna=True).compute())
        checks.append(Check(hemisphere, f"{name}_nonnegative", "PASS" if vmin >= -1e-8 else "FAIL",
                            f"min={vmin:.6g}, max={vmax:.6g}."))
    return checks


def aligned_frame(candidate: dict[str, pd.Series], reference: dict[str, pd.Series], full_index: pd.DatetimeIndex) -> pd.DataFrame:
    df = pd.DataFrame(index=full_index)
    df.index.name = "date"
    for metric in PLOT_ORDER:
        df[f"candidate_{metric}"] = candidate.get(metric, pd.Series(dtype=float)).reindex(full_index)
        df[f"reference_{metric}"] = reference.get(metric, pd.Series(dtype=float)).reindex(full_index)
    return df


def safe_ratio(num: float, den: float) -> float:
    return np.nan if not np.isfinite(num) or not np.isfinite(den) or abs(den) < 1e-12 else num / den


def make_summary(df: pd.DataFrame, final_window: int) -> pd.DataFrame:
    rows = []
    for metric in PLOT_ORDER:
        pair = pd.concat([df[f"candidate_{metric}"].rename("candidate"), df[f"reference_{metric}"].rename("reference")], axis=1).dropna()
        row = {"metric": metric, "units": DISPLAY_UNITS[metric].replace("$", ""), "n_common": int(len(pair)),
               "first_common_date": "", "last_common_date": "", "candidate_first": np.nan, "reference_first": np.nan,
               "candidate_last": np.nan, "reference_last": np.nan, "last_ratio": np.nan,
               "candidate_final_window_median": np.nan, "reference_final_window_median": np.nan,
               "final_window_ratio": np.nan, "bias_mean": np.nan, "rmse": np.nan,
               "nrmse_refmean": np.nan, "correlation": np.nan}
        if not pair.empty:
            row["first_common_date"] = pair.index[0].strftime("%Y-%m-%d")
            row["last_common_date"] = pair.index[-1].strftime("%Y-%m-%d")
            row["candidate_first"] = float(pair.candidate.iloc[0])
            row["reference_first"] = float(pair.reference.iloc[0])
            row["candidate_last"] = float(pair.candidate.iloc[-1])
            row["reference_last"] = float(pair.reference.iloc[-1])
            row["last_ratio"] = safe_ratio(row["candidate_last"], row["reference_last"])
            tail = pair.tail(max(1, final_window))
            cm = float(tail.candidate.median())
            rm = float(tail.reference.median())
            row["candidate_final_window_median"] = cm
            row["reference_final_window_median"] = rm
            row["final_window_ratio"] = safe_ratio(cm, rm)
            diff = pair.candidate - pair.reference
            row["bias_mean"] = float(diff.mean())
            rmse = float(np.sqrt(np.mean(np.square(diff.to_numpy(dtype=float)))))
            row["rmse"] = rmse
            ref_mean = float(np.mean(np.abs(pair.reference.to_numpy(dtype=float))))
            row["nrmse_refmean"] = safe_ratio(rmse, ref_mean)
            if len(pair) >= 3 and pair.candidate.std() > 0 and pair.reference.std() > 0:
                row["correlation"] = float(pair.candidate.corr(pair.reference))
        rows.append(row)
    return pd.DataFrame(rows)


def plot_health(df: pd.DataFrame, hemisphere: str, run_name: str, reference: str, outpath: Path) -> None:
    fig, axes = plt.subplots(4, 2, figsize=(14, 15), sharex=True)
    axes = axes.ravel()
    for ax, metric in zip(axes, PLOT_ORDER):
        ax.plot(df.index, df[f"candidate_{metric}"], label=run_name, linewidth=1.8)
        ax.plot(df.index, df[f"reference_{metric}"], label=reference, linewidth=1.5)
        ax.set_title(PLOT_LABELS[metric])
        ax.set_ylabel(DISPLAY_UNITS[metric])
        ax.grid(alpha=0.25)
    axes[0].legend(loc="best")
    axes[-1].set_xlabel("Date")
    axes[-2].set_xlabel("Date")
    fig.suptitle(f"{hemisphere} CICE run health: {run_name} vs {reference}", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.975))
    fig.savefig(outpath, dpi=180, bbox_inches="tight")
    plt.close(fig)


def overall_status(checks: list[Check]) -> str:
    statuses = {c.status for c in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def write_report(path: Path, *, args: argparse.Namespace, history_root: Path, candidate_root: Path,
                 reference_root: Path, start: pd.Timestamp, end: pd.Timestamp,
                 missing_dates: pd.DatetimeIndex, checks: list[Check], summaries: dict[str, pd.DataFrame]) -> None:
    lines = [f"CICE MODEL RUN HEALTH: {args.run_name} vs {args.reference_sim}", "=" * 72,
             f"candidate source : {history_root}", f"candidate output : {candidate_root}",
             f"reference root   : {reference_root} (read only)",
             f"comparison dates : {start.strftime('%Y-%m-%d')} -> {end.strftime('%Y-%m-%d')}",
             f"FI method        : {args.fi_method} (ispd={args.ispd_thresh:g}, W={args.bin_window}, N={args.bin_min_days})",
             f"SIE threshold    : {args.ice_threshold:g}", f"integrity status : {overall_status(checks)}", "",
             "Interpretation", "--------------",
             "The integrity status checks file continuity and physically valid field ranges.",
             "Candidate/reference ratios are recovery diagnostics, not pass/fail skill scores.",
             "For a run initialized from zero sea ice, values approaching 1 through time indicate",
             "movement toward the magnitude of the spun-up reference state for that diagnostic.",
             "SIE and mean SIC are computed transiently from read-only CICE histories because",
             "they are not currently persisted in the shuga CICE metrics registry.", ""]
    if len(missing_dates):
        preview = ", ".join(d.strftime("%Y-%m-%d") for d in missing_dates[:20])
        lines += [f"Missing candidate source dates ({len(missing_dates)}): {preview}", ""]
    lines += ["Integrity checks", "----------------"]
    for c in checks:
        lines.append(f"[{c.status:4s}] {c.hemisphere:>2s} {c.check}: {c.detail}")
    for hemi, summary in summaries.items():
        lines += ["", f"{hemi} final-window comparison", "-" * 34]
        for _, row in summary.iterrows():
            ratio = row["final_window_ratio"]
            ratio_text = "n/a" if not np.isfinite(ratio) else f"{ratio:.3f}"
            lines.append(f"{row['metric']:>3s}: candidate={row['candidate_final_window_median']:.6g}  reference={row['reference_final_window_median']:.6g}  ratio={ratio_text}  n={int(row['n_common'])}")
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    afim_root, history_root, reference_root, static_store = resolve_roots(args)
    hemispheres = list(dict.fromkeys(canonical_hemisphere(v) for v in args.hemispheres.split(",") if v.strip()))
    selected, start, end, missing_dates = discover_history_files(history_root, args.start_date, args.end_date)
    source_snapshot = snapshot_source([p for _, p in selected])
    start_s, end_s = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    candidate_root = afim_root / args.run_name
    reference_afim_root = reference_root.parent
    checks: list[Check] = [Check("--", "source_date_continuity", "PASS" if len(missing_dates) == 0 else "WARN",
                                 f"{len(selected)} source files; {len(missing_dates)} missing daily dates in requested window.")]
    if not args.skip_candidate_processing:
        process_candidate(args, history_root, afim_root, static_store, start, end, hemispheres)
    verify_source_unchanged(source_snapshot)
    checks.append(Check("--", "source_files_unchanged", "PASS", "Candidate NetCDF source files were not moved, deleted, or modified."))
    outdir = Path(args.outdir).expanduser() if args.outdir else candidate_root / "health" / args.reference_sim / f"{start_s}_{end_s}"
    outdir.mkdir(parents=True, exist_ok=True)
    full_index = pd.date_range(start, end, freq="D")
    summaries: dict[str, pd.DataFrame] = {}
    for hemi in hemispheres:
        checks.extend(candidate_physical_checks(sim_root=candidate_root, hemisphere=hemi, start=start_s, end=end_s,
                                               afim_root=afim_root, static_store=static_store, args=args))
        candidate = load_health_series(sim_name=args.run_name, sim_root=candidate_root, hemisphere=hemi,
                                       start=start_s, end=end_s, afim_root=afim_root, static_store=static_store,
                                       args=args, allow_missing_metrics=False, checks=checks)
        reference = load_health_series(sim_name=args.reference_sim, sim_root=reference_root, hemisphere=hemi,
                                       start=start_s, end=end_s, afim_root=reference_afim_root, static_store=static_store,
                                       args=args, allow_missing_metrics=True, checks=checks)
        df = aligned_frame(candidate, reference, full_index)
        df.to_csv(outdir / f"timeseries_{hemi}.csv", float_format="%.8g")
        summary = make_summary(df, args.final_window)
        summary.insert(0, "hemisphere", hemi)
        summary.to_csv(outdir / f"summary_{hemi}.csv", index=False, float_format="%.8g")
        summaries[hemi] = summary
        plot_health(df, hemi, args.run_name, args.reference_sim, outdir / f"health_{hemi}.png")
    pd.DataFrame([c.__dict__ for c in checks]).to_csv(outdir / "sanity_checks.csv", index=False)
    write_report(outdir / "health_report.txt", args=args, history_root=history_root, candidate_root=candidate_root,
                 reference_root=reference_root, start=start, end=end, missing_dates=missing_dates,
                 checks=checks, summaries=summaries)
    print("\nHealth comparison complete")
    print(f"  run       : {args.run_name}")
    print(f"  reference : {args.reference_sim}")
    print(f"  dates     : {start_s} -> {end_s}")
    print(f"  status    : {overall_status(checks)}")
    print(f"  output    : {outdir}")


if __name__ == "__main__":
    main()
