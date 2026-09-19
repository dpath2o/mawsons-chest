#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys

THIS       = Path(__file__).resolve()
FLOES_ROOT = THIS.parents[2]
PARENT     = FLOES_ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from floes.config import previous_complete_month  # noqa: E402
from floes.io.download import (  # noqa: E402
    bremen_cli,
    build_bremen_amsr2_jobs,
    build_esa_cci_sit_jobs,
    build_nsidc_g02202_jobs,
    download_jobs,
    esa_cci_sit_cli,
    nsidc_cli,
    write_manifest,
)


def _recent_months(year: int, month: int, count: int) -> list[tuple[int, int]]:
    """Return ``count`` calendar months ending at ``year, month``."""
    out: list[tuple[int, int]] = []
    y, m = int(year), int(month)
    for _ in range(count):
        out.append((y, m))
        m -= 1
        if m == 0:
            y -= 1
            m = 12
    return out


def all_cli(argv: list[str] | None = None) -> int:
    default_year, default_month = previous_complete_month()
    p = argparse.ArgumentParser(
        description="Update the observational archives used by floes in one copyq job."
    )
    p.add_argument(
        "--dest-root",
        type=Path,
        default=Path("/g/data/gv90/da1339/SeaIce"),
        help="Existing SeaIce archive root on Gadi.",
    )
    p.add_argument("--start-year", type=int, default=1979)
    p.add_argument("--year", type=int, default=default_year)
    p.add_argument("--month", type=int, choices=range(1, 13), default=default_month)
    p.add_argument("--bremen-lookback-months", type=int, default=4)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--min-bytes", type=int, default=10_000)
    p.add_argument("--manifest-file", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    jobs = []

    # NSIDC G02202 V6:
    # retain the established local hierarchy and use non-overlapping yearly
    # daily aggregates as the canonical archive.  Do not download the large
    # rolling 1978-present monthly aggregate.
    jobs.extend(
        build_nsidc_g02202_jobs(
            dest_root=args.dest_root / "NSIDC",
            hemis=["north", "south"],
            start_year=args.start_year,
            end_year=args.year,
            daily_mode="aggregate",
            monthly_mode="none",
            include_ancillary=True,
        )
    )

    # University of Bremen AMSR2:
    # refresh a short current window while preserving the established
    # University_Bremen/AMSR2/asi_daygrid_swath/s6250 hierarchy.
    recent = _recent_months(args.year, args.month, args.bremen_lookback_months)
    for year in sorted({y for y, _ in recent}):
        months = [m for y, m in recent if y == year]
        jobs.extend(
            build_bremen_amsr2_jobs(
                dest_root=args.dest_root,
                year=year,
                months=months,
            )
        )

    # ESA CCI SIT:
    # check the newest available SH year for each established sensor and
    # preserve ESA/CCI/thickness/{L2P,L3C}/<sensor>/v4.0/SH/...
    jobs.extend(
        build_esa_cci_sit_jobs(
            dest_root=args.dest_root,
            levels=("L2P", "L3C"),
            sensors=("envisat", "cryosat2", "sentinel3a", "sentinel3b"),
            hemisphere="SH",
        )
    )

    jobs = sorted({str(job.dest): job for job in jobs}.values(), key=lambda job: str(job.dest))
    print(f"Planned files across all floes observation sources: {len(jobs)}")
    if args.manifest_file is not None:
        write_manifest(jobs, args.manifest_file)
        print(f"Wrote manifest: {args.manifest_file}")
    if args.dry_run:
        for job in jobs:
            print(f"{job.url}\t{job.dest}")
        return 0
    if not jobs:
        raise RuntimeError("Remote archive discovery returned no matching observation files.")
    return download_jobs(
        jobs,
        workers=args.workers,
        retries=args.retries,
        min_bytes=args.min_bytes,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download observational products used by floes.")
    sub = p.add_subparsers(dest="product", required=True)
    sub.add_parser("nsidc-g02202", help="Download NSIDC NOAA/NSIDC CDR G02202 products")
    sub.add_parser("bremen-amsr2", help="Download University of Bremen AMSR2 SIC products")
    sub.add_parser("esa-cci-sit", help="Download ESA CCI L2P/L3C sea-ice-thickness products")
    sub.add_parser("all", help="Update all floes observational archives (intended for Gadi copyq)")
    # Parse the product command, then pass remaining args to the dedicated parser.
    args, rest = p.parse_known_args(argv)
    if args.product == "nsidc-g02202":
        return nsidc_cli(rest)
    if args.product == "bremen-amsr2":
        return bremen_cli(rest)
    if args.product == "esa-cci-sit":
        return esa_cci_sit_cli(rest)
    if args.product == "all":
        return all_cli(rest)
    raise ValueError(args.product)

if __name__ == "__main__":
    raise SystemExit(main())
