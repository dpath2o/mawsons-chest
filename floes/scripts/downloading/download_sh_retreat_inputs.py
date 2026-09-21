#!/usr/bin/env python3
from __future__ import annotations
import argparse, calendar, shutil, subprocess, tempfile
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr

CMEMS_2D    = "cmems_mod_glo_phy_anfc_0.083deg_P1D-m"
CMEMS_TEMP  = "cmems_mod_glo_phy-thetao_anfc_0.083deg_P1D-m"
CMEMS_SALT  = "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m"
CMEMS_CUR   = "cmems_mod_glo_phy-cur_anfc_0.083deg_P1D-m"
SEAICE_VARS = ("siconc","sithick","usi","vsi","sialb","siage","sisnthick")
ERA5_CODES  = {"10u":"u10","10v":"v10","2t":"t2m","2d":"d2m","msl":"msl"}

def args():
    p=argparse.ArgumentParser()
    p.add_argument("--end-date", default = (date.today()-timedelta(days=1)).isoformat())
    p.add_argument("--window-days", type = int, default = 91)
    p.add_argument("--comparison-years", type = int, default = 3)
    p.add_argument("--lat-min", type = float, default = -80.0)
    p.add_argument("--lat-max", type = float, default = -45.0)
    p.add_argument("--depth-max", type = float, default = 500.0)
    p.add_argument("--seaice-root", type = Path, default = Path("/g/data/gv90/da1339/SeaIce/CMEMS/0p083/daily"))
    p.add_argument("--ocean-root", type = Path, default =Path("/g/data/gv90/da1339/afim_input/ORAS/daily/org"))
    p.add_argument("--atmos-root", type = Path, default = Path("/g/data/gv90/da1339/afim_input/ERA5/daily/org"))
    p.add_argument("--era5-root", type = Path, default = Path("/g/data/rt52"))
    p.add_argument("--overwrite", action = "store_true")
    p.add_argument("--dry-run", action = "store_true")
    return p.parse_args()

def same_md(d,year):
    return pd.Timestamp(year=year,month=d.month,day=min(d.day,calendar.monthrange(year,d.month)[1]))

def weeks(start,end):
    cur=start.normalize()
    while cur<=end:
        stop=min(cur+pd.Timedelta(days=6),end)
        yield cur,stop
        cur=stop+pd.Timedelta(days=1)

def cmems_api():
    import copernicusmarine
    return copernicusmarine

def subset(cm, dataset, variables, start, end, out, latmin, latmax, depthmax = None, overwrite = False, dry = False):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        print("SKIP", out)
        return out
    kwargs = dict(dataset_id=dataset,
                  variables=list(variables),
                  start_datetime=start.strftime("%Y-%m-%dT00:00:00"),
                  end_datetime=end.strftime("%Y-%m-%dT23:59:59"),
                  minimum_longitude=-180.0,
                  maximum_longitude=179.9166717529297,
                  minimum_latitude=latmin,
                  maximum_latitude=latmax,
                  coordinates_selection_method="inside",
                  output_directory=out.parent,
                  output_filename=out.name,
                  disable_progress_bar=True)
    if depthmax is not None:
        kwargs["minimum_depth"] = 0.5
        kwargs["maximum_depth"] = float(depthmax)
    print(f"CMEMS API: dataset={dataset} {start.date()}..{end.date()} vars={','.join(variables)} -> {out}")
    if dry:
        print("  ", kwargs)
        return out
    cm.subset(**kwargs)
    if not out.exists():
        raise RuntimeError(f"CMEMS subset returned but expected output was not created: {out}")
    return out

def ocean_week(cm,start,end,out,latmin,latmax,depthmax,overwrite,dry):
    if out.exists() and not overwrite:
        print("SKIP",out); return out
    out.parent.mkdir(parents=True,exist_ok=True)
    if dry:
        for ds,vs in ((CMEMS_TEMP,("thetao",)),(CMEMS_SALT,("so",)),(CMEMS_CUR,("uo","vo"))):
            subset(cm, ds, vs, start, end, out.parent/f"DRY_{vs[0]}.nc", latmin, latmax, depthmax, overwrite, True)
        print("Would merge ->",out); return out
    tmp_root = Path("/g/data/gv90/da1339/tmp/cmems")
    tmp_root.mkdir(parents = True, exist_ok = True)
    with tempfile.TemporaryDirectory(prefix = "floes_cmems_", dir = tmp_root) as td:
    # with tempfile.TemporaryDirectory(prefix="floes_cmems_") as td:
        td=Path(td); parts=[]
        for tag,ds,vs in (("thetao",CMEMS_TEMP,("thetao",)),("so",CMEMS_SALT,("so",)),("uv",CMEMS_CUR,("uo","vo"))):
            q=td/f"{tag}.nc"; parts.append(q)
            subset(cm,ds,vs,start,end,q,latmin,latmax,depthmax,True,False)
        opened=[xr.open_dataset(q,decode_timedelta=False) for q in parts]
        try:
            ds=xr.merge(opened,compat="override",join="outer")
            ds.attrs["source"]="Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY_001_024"
            enc={n:{"zlib":True,"complevel":2,"shuffle":True} for n in ds.data_vars}
            ds.to_netcdf(out,encoding=enc)
        finally:
            for d in opened: d.close()
    print("WROTE",out); return out

def era5_family_files(root, family, code, start, end):
    files = []
    for year in range(start.year, end.year + 1):
        directory = (root / family / "single-levels" / "reanalysis" / code / f"{year:04d}")
        files    += sorted(directory.glob(f"{code}_{family}_oper_sfc_{year:04d}*.nc"))
    return files

def open_era5_component(root, code, name, start, end, latmin, latmax):
    pieces = []
    # ERA5T first, final ERA5 second.
    # If timestamps overlap, later duplicate removal therefore retains ERA5.
    for family in ("era5t", "era5"):
        files = era5_family_files(root, family, code, start, end)
        for path in files:
            with xr.open_dataset(path, decode_timedelta = False) as ds:
                if name not in ds:
                    continue
                da = ds[name]
                da = south(da, latmin, latmax)
                da = da.sel(time = slice(start, end + pd.Timedelta(hours = 23, minutes = 59)))
                if da.sizes.get("time", 0) == 0:
                    continue
                pieces.append(da.load())
    if not pieces:
        raise FileNotFoundError(f"No ERA5/ERA5T data found for {name} ({code}) over {start.date()}..{end.date()}")
    combined = xr.concat(pieces, dim = "time")
    # Remove overlapping ERA5/ERA5T timestamps.
    # Because ERA5 was appended after ERA5T, keep='last'
    # preferentially retains final ERA5.
    index    = pd.DatetimeIndex(combined["time"].values)
    keep     = ~index.duplicated(keep = "last")
    combined = combined.isel(time = np.flatnonzero(keep))
    combined = combined.sortby("time")
    return combined

def south(da,latmin,latmax):
    n="latitude" if "latitude" in da.coords else "lat"; lat=da[n]
    sl=slice(latmax,latmin) if float(lat[0])>float(lat[-1]) else slice(latmin,latmax)
    return da.sel({n:sl})

def rh(t,td):
    tc=t-273.15; dc=td-273.15
    out=100*np.exp(17.625*dc/(243.04+dc)-17.625*tc/(243.04+tc))
    out=out.clip(0,100); out.name="rh2m"; out.attrs={"units":"%","long_name":"2 m relative humidity"}
    return out

def era5_week(root, start, end, out, latmin, latmax, overwrite, dry):
    if out.exists() and not overwrite:
        print("SKIP", out)
        return out
    out.parent.mkdir(parents = True, exist_ok = True)
    if dry:
        print("Would stage ERA5", start.date(), end.date(), "->", out)
        return out
    fields = {}
    for code, name in ERA5_CODES.items():
        da           = open_era5_component(root, code, name, start, end, latmin, latmax)
        fields[name] = (da.resample(time="1D").mean(skipna=True))
    outds                 = xr.Dataset(fields)
    outds["rh2m"]         = rh(outds.t2m, outds.d2m)
    outds.attrs["source"] = ("NCI ERA5/ERA5T /g/data/rt52; final ERA5 preferred where timestamps overlap")
    enc                   = {name: {"zlib" : True, "complevel": 2, "shuffle"  : True} for name in outds.data_vars}
    outds.to_netcdf(out, encoding = enc)
    print("WROTE", out)
    return out

def main():
    a   = args()
    end = pd.Timestamp(a.end_date).normalize()
    cm  = cmems_api()
    for off in range(a.comparison_years):
        y = end.year-off
        e = same_md(end,y)
        s = e-pd.Timedelta(days=a.window_days-1)
        print(f"\n=== {y}: {s.date()}..{e.date()} ===")
        for w0,w1 in weeks(s,e):
            tag = f"{w0:%Y%m%d}_{w1:%Y%m%d}"
            subset(cm,CMEMS_2D,SEAICE_VARS,w0,w1,a.seaice_root/f"{y:04d}"/f"{tag}_CMEMS_0p083_seaice.nc", a.lat_min, a.lat_max, None, a.overwrite, a.dry_run)
            ocean_week(cm,w0,w1,a.ocean_root/f"{y:04d}"/f"{tag}_CMEMS_0p083_ocean_0-500m.nc", a.lat_min, a.lat_max, a.depth_max, a.overwrite, a.dry_run)
            era5_week(a.era5_root,w0,w1,a.atmos_root/f"{y:04d}"/f"{tag}_ERA5_daily.nc", a.lat_min, a.lat_max, a.overwrite, a.dry_run)
    return 0

if __name__=="__main__":
    raise SystemExit(main())
