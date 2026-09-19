#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, tempfile, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CMR = "https://cmr.earthdata.nasa.gov/search"
DEFAULT_ROOT = Path("/g/data/gv90/da1339/SeaIce/ICESat2/ATL20/V005")
RX = re.compile(r"^ATL20-(?P<hemi>01|02)_(?P<date>\d{8})\d{6}_[^_]+_005_(?P<rev>\d{2})\.h5$")

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent" : "floes-atl20-downloader/1.0"})
    with urllib.request.urlopen(req, timeout = 120) as r:
        return json.load(r)

def concept_id():
    q = urllib.parse.urlencode({"short_name" : "ATL20",
                                "version"    : "005",
                                "provider"   : "NSIDC_CPRD",
                                "page_size"  : 20})
    entries = fetch_json(f"{CMR}/collections.json?{q}").get("feed",{}).get("entry",[])
    if not entries:
        raise RuntimeError("CMR returned no ATL20 v005 collection")
    return entries[0]["id"]

def granule_urls(cid):
    urls, page = set(), 1
    while True:
        q = urllib.parse.urlencode({"collection_concept_id" : cid,
                                    "page_size"             : 200,
                                    "page_num"              : page})
        entries = fetch_json(f"{CMR}/granules.json?{q}").get("feed",{}).get("entry",[])
        if not entries:
            break
        for e in entries:
            cand=[]
            for link in e.get("links",[]):
                href=link.get("href","")
                clean=href.split("?",1)[0]
                if clean.lower().endswith(".h5") and "ATL20-" in clean:
                    cand.append(href)
            cand.sort(key = lambda u:("data.nsidc.earthdatacloud.nasa.gov" not in u,u))
            if cand:
                urls.add(cand[0])
        if len(entries)<200: break
        page += 1
    return sorted(urls)

def destination(root,url):
    name = Path(urllib.parse.urlparse(url).path).name
    m    = RX.match(name)
    if not m: raise ValueError(f"Unrecognised ATL20 v005 filename: {name}")
    hemi = "NH" if m.group("hemi")=="01" else "SH"
    d    = m.group("date")
    return root/hemi/d[:4]/d[4:6]/name

def valid_h5(path,min_bytes):
    if not path.exists() or path.stat().st_size < min_bytes: return False
    try:
        with path.open("rb") as f: return f.read(8)==b"\x89HDF\r\n\x1a\n"
    except OSError:
        return False

def download_one(url,dest,min_bytes):
    dest.parent.mkdir(parents = True, exist_ok = True)
    if valid_h5(dest,min_bytes): return "skipped",str(dest)
    cookies = Path.home()/".urs_cookies"
    cookies.touch(exist_ok=True); os.chmod(cookies,0o600)
    with tempfile.NamedTemporaryFile(prefix = dest.name+".", suffix = ".part", dir = dest.parent, delete = False) as tf:
        tmp = Path(tf.name)
    cmd=["curl", "-fL", "--retry", "5", "--retry-delay", "5", "--connect-timeout", "30", "--max-time", "1800",
         "--netrc", "--cookie", str(cookies), "--cookie-jar", str(cookies), "--output", str(tmp), url]
    try:
        subprocess.run(cmd,check = True)
        if not valid_h5(tmp, min_bytes): raise RuntimeError(f"Invalid HDF5: {tmp}")
        tmp.replace(dest); return "downloaded",str(dest)
    except Exception:
        tmp.unlink(missing_ok=True); raise

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dest-root", type = Path, default = DEFAULT_ROOT)
    p.add_argument("--workers", type = int , default = 4)
    p.add_argument("--min-bytes", type = int, default = 50000)
    p.add_argument("--hemisphere", choices = ("all","SH","NH"), default = "all")
    p.add_argument("--dry-run", action = "store_true")
    p.add_argument("--manifest", type = Path, default = None)
    a    = p.parse_args()
    cid  = concept_id()
    urls = granule_urls(cid)
    jobs = []
    for u in urls:
        d = destination(a.dest_root,u)
        if a.hemisphere == "all" or a.hemisphere in d.parts: jobs.append((u,d))
    print(f"ATL20 v005 collection : {cid}")
    print(f"CMR HDF5 granules     : {len(urls)}")
    print(f"Selected granules     : {len(jobs)}")
    print(f"Destination root      : {a.dest_root}")
    if a.manifest:
        a.manifest.parent.mkdir(parents = True, exist_ok = True)
        a.manifest.write_text("\\n".join(f"{u}\\t{d}" for u,d in jobs)+"\\n")
    if a.dry_run:
        for u,d in jobs: print(f"{u}\\t{d}")
        return 0
    if not (Path.home()/".netrc").exists():
        raise SystemExit("ERROR: ~/.netrc required for NASA Earthdata Login; chmod 600 ~/.netrc")
    counts = {"downloaded":0,"skipped":0,"failed":0}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(download_one,u,d,a.min_bytes):(u,d) for u,d in jobs}
        for fut in as_completed(futs):
            _,d = futs[fut]
            try:
                status , path  = fut.result()
                counts[status]+=1
                print(f"{status.upper():10s} {path}",flush=True)
            except Exception as e:
                counts["failed"]+=1; print(f"FAILED     {d}: {e}",file=sys.stderr,flush=True)
    print(f"Finished: downloaded = {counts['downloaded']} skipped = {counts['skipped']} failed = {counts['failed']}")
    return 1 if counts["failed"] else 0

if __name__=="__main__":
    raise SystemExit(main())
