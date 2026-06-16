from __future__ import annotations
import argparse
import concurrent.futures as cf
import html
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (compatible; floes-gadi-downloader/0.1)"
HEMI_TO_GRID = {"north": "psn25", "south": "pss25"}

@dataclass(frozen=True)
class DownloadJob:
    url: str
    dest: Path

def fetch_text(url: str, timeout: int = 60) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")

def list_links(url: str) -> list[str]:
    text = fetch_text(url)
    hrefs = re.findall(r'href="([^"]+)"', text, flags=re.I)
    out: list[str] = []
    for href in hrefs:
        href = html.unescape(href)
        if href in ("../", "./") or href.startswith("?"):
            continue
        out.append(href)
    return sorted(set(out))

def list_nc(url: str) -> list[str]:
    return [name for name in list_links(url) if name.endswith(".nc")]

def choose_yearly_daily_aggregate(files: list[str], grid: str, year: int) -> str | None:
    rx = re.compile(rf"sic_{grid}_{year}0101-{year}\d{{4}}_v\d{{2}}r\d{{2}}\.nc$")
    cands = sorted(f for f in files if rx.fullmatch(f))
    return cands[-1] if cands else None

def choose_period_monthly_aggregate(files: list[str], grid: str) -> str | None:
    rx = re.compile(rf"sic_{grid}_\d{{6}}-\d{{6}}_v\d{{2}}r\d{{2}}\.nc$")
    cands = sorted(f for f in files if rx.fullmatch(f))
    return cands[-1] if cands else None

def choose_daily_individual(files: list[str], grid: str, year: int) -> list[str]:
    rx = re.compile(rf"sic_{grid}_{year}\d{{4}}_[A-Za-z0-9]+_v\d{{2}}r\d{{2}}\.nc$")
    return sorted(f for f in files if rx.fullmatch(f))

def choose_monthly_individual(files: list[str], grid: str, start_ym: int, end_ym: int) -> list[str]:
    rx = re.compile(rf"sic_{grid}_(\d{{6}})_[A-Za-z0-9]+_v\d{{2}}r\d{{2}}\.nc$")
    out: list[str] = []
    for name in files:
        m = rx.fullmatch(name)
        if not m:
            continue
        ym = int(m.group(1))
        if start_ym <= ym <= end_ym:
            out.append(name)
    return sorted(out)

def build_nsidc_g02202_jobs(*,
                            base_url: str = "https://noaadata.apps.nsidc.org/NOAA",
                            version: str = "G02202_V6",
                            dest_root: Path,
                            hemis: list[str],
                            start_year: int,
                            end_year: int,
                            daily_mode: str = "aggregate",
                            monthly_mode: str = "aggregate",
                            include_ancillary: bool = True) -> list[DownloadJob]:
    """Build NSIDC G02202 download jobs using HTTP directory discovery.

    This follows the robust AFIM pattern: inspect the index, choose matching NetCDF
    products, write a manifest if requested, and only then download.
    """
    version_root = f"{base_url.rstrip('/')}/{version}"
    jobs: list[DownloadJob] = []
    if include_ancillary:
        anc_url = f"{version_root}/ancillary/"
        try:
            anc_files = list_nc(anc_url)
        except HTTPError as exc:
            print(f"WARNING: cannot list ancillary URL {anc_url}: {exc}", file=sys.stderr)
            anc_files = []
        for hemi in hemis:
            grid = HEMI_TO_GRID[hemi]
            pats = [re.compile(rf"G02202-ancillary-{grid}-v\d{{2}}r\d{{2}}\.nc$"),
                    re.compile(rf"G02202-ancillary-{grid}-daily-invalid-ice-v\d{{2}}r\d{{2}}\.nc$")]
            for name in anc_files:
                if any(p.fullmatch(name) for p in pats):
                    jobs.append(DownloadJob(urljoin(anc_url, name), dest_root / version / hemi / "ancillary" / name))
    for hemi in hemis:
        grid = HEMI_TO_GRID[hemi]
        if daily_mode == "aggregate":
            agg_url = f"{version_root}/{hemi}/aggregate/"
            try:
                agg_files = list_nc(agg_url)
            except HTTPError as exc:
                print(f"WARNING: cannot list {agg_url}: {exc}", file=sys.stderr)
                agg_files = []
            for year in range(start_year, end_year + 1):
                name = choose_yearly_daily_aggregate(agg_files, grid, year)
                if name is None:
                    print(f"WARNING: no yearly daily aggregate found for {hemi} {year}", file=sys.stderr)
                    continue
                jobs.append(DownloadJob(urljoin(agg_url, name), dest_root / version / hemi / "aggregate" / name))
        elif daily_mode == "individual":
            for year in range(start_year, end_year + 1):
                daily_url = f"{version_root}/{hemi}/daily/{year}/"
                try:
                    files = list_nc(daily_url)
                except HTTPError as exc:
                    print(f"WARNING: cannot list {daily_url}: {exc}", file=sys.stderr)
                    continue
                for name in choose_daily_individual(files, grid, year):
                    jobs.append(DownloadJob(urljoin(daily_url, name), dest_root / version / hemi / "daily" / name))
        if monthly_mode == "aggregate":
            agg_url = f"{version_root}/{hemi}/aggregate/"
            try:
                agg_files = list_nc(agg_url)
            except HTTPError as exc:
                print(f"WARNING: cannot list {agg_url}: {exc}", file=sys.stderr)
                agg_files = []
            name = choose_period_monthly_aggregate(agg_files, grid)
            if name is None:
                print(f"WARNING: no period monthly aggregate found for {hemi}", file=sys.stderr)
            else:
                jobs.append(DownloadJob(urljoin(agg_url, name), dest_root / version / hemi / "aggregate" / name))
        elif monthly_mode == "individual":
            mon_url = f"{version_root}/{hemi}/monthly/"
            files = list_nc(mon_url)
            start_ym = start_year * 100 + 1
            end_ym = end_year * 100 + 12
            for name in choose_monthly_individual(files, grid, start_ym, end_ym):
                jobs.append(DownloadJob(urljoin(mon_url, name), dest_root / version / hemi / "monthly" / name))
    dedup: dict[str, DownloadJob] = {}
    for job in jobs:
        dedup[str(job.dest)] = job
    return list(dedup.values())

def download_one(job: DownloadJob, *, min_bytes: int = 10_000, retries: int = 4) -> tuple[str, str, str, str]:
    job.dest.parent.mkdir(parents=True, exist_ok=True)
    if job.dest.exists() and job.dest.stat().st_size >= min_bytes:
        return ("skip", job.url, str(job.dest), str(job.dest.stat().st_size))
    tmp = job.dest.with_suffix(job.dest.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(job.url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=180) as src, open(tmp, "wb") as out:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            size = tmp.stat().st_size
            if size < min_bytes:
                raise IOError(f"download too small: {size} bytes")
            tmp.replace(job.dest)
            return ("download", job.url, str(job.dest), str(size))
        except Exception as exc:  # noqa: BLE001 - report and retry all transfer failures
            last_err = exc
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            time.sleep(min(30, 2 * attempt))
    return ("error", job.url, str(job.dest), repr(last_err))

def write_manifest(jobs: list[DownloadJob], manifest_file: Path) -> None:
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    with manifest_file.open("w", encoding="utf-8") as f:
        for job in sorted(jobs, key=lambda j: str(j.dest)):
            f.write(f"{job.url}\t{job.dest}\n")

def download_jobs(jobs: list[DownloadJob], *, workers: int = 4, retries: int = 4, min_bytes: int = 10_000) -> int:
    ok = skipped = failed = 0
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(download_one, job, min_bytes=min_bytes, retries=retries) for job in jobs]
        for fut in cf.as_completed(futs):
            status, url, path, info = fut.result()
            if status == "download":
                ok += 1
                print(f"DOWNLOADED\t{info}\t{path}")
            elif status == "skip":
                skipped += 1
                print(f"SKIPPED\t{info}\t{path}")
            else:
                failed += 1
                print(f"ERROR\t{path}\t{info}\t{url}", file=sys.stderr)
    print(f"Summary: downloaded={ok}, skipped={skipped}, failed={failed}")
    return 1 if failed else 0

def download_nsidc_g02202(**kwargs) -> int:
    jobs = build_nsidc_g02202_jobs(**kwargs)
    manifest_file = kwargs.get("manifest_file")
    if manifest_file:
        write_manifest(jobs, Path(manifest_file))
    return download_jobs(jobs)

def nsidc_cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Discover and download available NSIDC G02202 files.")
    p.add_argument("--base-url", default="https://noaadata.apps.nsidc.org/NOAA")
    p.add_argument("--version", default="G02202_V6")
    p.add_argument("--dest-root", required=True, type=Path)
    p.add_argument("--start-year", type=int, required=True)
    p.add_argument("--end-year", type=int, required=True)
    p.add_argument("--hemis", nargs="+", choices=["north", "south"], default=["south"])
    p.add_argument("--daily", choices=["aggregate", "individual", "none"], default="none")
    p.add_argument("--monthly", choices=["aggregate", "individual", "none"], default="aggregate")
    p.add_argument("--ancillary", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--min-bytes", type=int, default=10_000)
    p.add_argument("--manifest-file", type=Path, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    jobs = build_nsidc_g02202_jobs(base_url          = args.base_url,
                                   version           = args.version,
                                   dest_root         = args.dest_root,
                                   hemis             = args.hemis,
                                   start_year        = args.start_year,
                                   end_year          = args.end_year,
                                   daily_mode        = args.daily,
                                   monthly_mode      = args.monthly,
                                   include_ancillary = args.ancillary)
    jobs = sorted(jobs, key=lambda j: str(j.dest))
    print(f"Planned files: {len(jobs)}")
    if args.manifest_file is not None:
        write_manifest(jobs, args.manifest_file)
        print(f"Wrote manifest: {args.manifest_file}")
    if args.dry_run:
        for job in jobs:
            print(f"{job.url}\t{job.dest}")
        return 0
    return download_jobs(jobs, workers = args.workers, retries = args.retries, min_bytes = args.min_bytes)
