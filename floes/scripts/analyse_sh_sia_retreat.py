#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
THIS=Path(__file__).resolve()
FLOES_ROOT=THIS.parents[1]
PARENT=FLOES_ROOT.parent
if str(PARENT) not in sys.path: sys.path.insert(0,str(PARENT))
from floes.config import default_config  # noqa: E402
from floes.observations.nsidc import NSIDCReader  # noqa: E402

EXCLUDED_RANK_YEARS = {1984, 1985}

def pltmod():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt

def args():
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,default=2026)
    p.add_argument("--search-start",default="07-15")
    p.add_argument("--search-end",default="09-15")
    p.add_argument("--change-days",type=int,default=7)
    p.add_argument("--composite-days",type=int,default=7)
    p.add_argument("--clim-start",type=int,default=1979)
    p.add_argument("--clim-end",type=int,default=2018)
    p.add_argument("--seaice-root",type=Path,default=Path("/g/data/gv90/da1339/SeaIce"))
    p.add_argument("--nsidc-daily-base",type=Path,default=Path("/g/data/gv90/da1339/SeaIce"))
    p.add_argument("--ocean-root",type=Path,default=Path("/g/data/gv90/da1339/afim_input/ORAS/daily/org"))
    p.add_argument("--fig-dir",type=Path,default=FLOES_ROOT/"figs"/"sh_sia_retreat_202608")
    p.add_argument("--markdown",type=Path,default=FLOES_ROOT/"docs"/"sh_sia_retreat_202608.md")
    return p.parse_args()

def climatology(series,start,end):
    idx       = pd.DatetimeIndex(series.index)
    s         = series[~((idx.month==2) & (idx.day==29))]
    f         = pd.DataFrame({"value":s.values}, index = pd.DatetimeIndex(s.index))
    f["year"] = f.index.year
    f["md"]   = f.index.strftime("%m-%d")
    return f[(f.year>=start)&(f.year<=end)].groupby("md").value.mean()

def event_significance(da,a,outdir):
    s          = da.to_series().dropna().sort_index()
    clim       = climatology(s, a.clim_start, a.clim_end)
    f          = pd.DataFrame({"SIA":s.values}, index = pd.DatetimeIndex(s.index))
    f["md"]    = f.index.strftime("%m-%d")
    f["anom"]  = f.SIA-f.md.map(clim)
    q          = f.loc[pd.Timestamp(f"{a.year}-{a.search_start}"):pd.Timestamp(f"{a.year}-{a.search_end}")].copy()
    q["delta"] = q.SIA.diff(a.change_days)
    end        = q.delta.idxmin()
    start      = end-pd.Timedelta(days = a.change_days)
    change     = float(q.loc[end,"delta"])
    EXCLUDED_RANK_YEARS = {1984, 1985}
    minima = []
    allchg = []
    for y in sorted(set(f.index.year)):
        sub = f.loc[pd.Timestamp(f"{y}-{a.search_start}"):pd.Timestamp(f"{y}-{a.search_end}"), "SIA"]
        d = sub.diff(a.change_days).dropna()
        if len(d):
            minval = float(d.min())
            mindate = d.idxmin()
            minima.append((y, minval, mindate))
            if y not in EXCLUDED_RANK_YEARS:
                allchg.extend(float(v) for v in d.values)
    # ranking years exclude known bad mid-1980s artefacts
    valid_minima = [(y, v, t) for (y, v, t) in minima if y not in EXCLUDED_RANK_YEARS]
    years = np.array([y for y, _, _ in valid_minima])
    vals = np.array([v for _, v, _ in valid_minima])
    # 2026 rank among valid years only
    order = np.argsort(vals)   # most negative first
    rank = int(np.where(years[order] == a.year)[0][0] + 1)
    this = float(vals[years == a.year][0])
    percentile = 100 * np.mean(np.asarray(allchg) <= this)
    # strongest and second strongest valid retreat years
    best_idx = order[0]
    second_idx = order[1]
    best_year = int(years[best_idx])
    best_val = float(vals[best_idx])
    second_year = int(years[second_idx])
    second_val = float(vals[second_idx])
    plt    = pltmod()
    fig,ax = plt.subplots(2, 1, figsize = (11,8))
    for y in sorted(set(f.index.year))[-20:]:
        g = f.loc[pd.Timestamp(y,7,15):pd.Timestamp(y,9,30)]
        if g.empty:
            continue
        x = pd.DatetimeIndex(g.index).dayofyear
        ax[0].plot(x,g.anom,color = "orange" if y==a.year else "0.72", lw = 2.5 if y == a.year else .8)
    ax[0].axvspan(start.dayofyear,end.dayofyear,color="0.9")
    ax[0].axhline(0,color="0.4",lw=.7)
    ax[0].set_ylabel(r"SIA anomaly (million km$^2$)")
    ax[0].set_title("Southern Hemisphere daily SIA anomaly")
    sel = years == a.year
    ax[1].scatter(years, vals, s=24, color="0.45", label="_nolegend_")
    # 2026 point
    sel = years == a.year
    ax[1].scatter(years[sel], vals[sel], s = 80, color = "orange", edgecolor = "0.25", zorder = 4, label = f"{a.year}")
    # strongest valid retreat
    ax[1].scatter([best_year], [best_val], s = 90, color = "red", edgecolor = "0.2", zorder = 5, label = f"Strongest valid retreat: {best_year}")
    # second strongest valid retreat
    ax[1].scatter([second_year], [second_val], s = 90, color = "purple", edgecolor = "0.2", zorder = 5, label = f"Second strongest valid retreat: {second_year}")
    ax[1].axhline(this, color = "orange", ls = "--", lw = .9)
    ax[1].set_xlabel("Year")
    ax[1].set_ylim(-1.0, 0.0)
    ax[1].set_ylabel(fr"Most negative {a.change_days}-day SIA change (million km$^2$)")
    ax[1].set_title(f"{a.search_start}–{a.search_end}; {a.year} rank {rank}/{len(valid_minima)} (excluding 1984–1985 artefacts)")
    ax[1].grid(axis = "y", color = "0.9", lw = .5)
    ax[1].legend(frameon = False, loc = "lower left",)
    out = outdir / f"NSIDC_SH_SIA_{a.change_days}day_retreat_significance_{a.year}.png"
    fig.savefig(out, dpi = 200, bbox_inches = "tight", facecolor = "white")
    plt.close(fig)
    return dict(
        start = start,
        end = end,
        change = change,
        rank = rank,
        n = len(valid_minima),
        percentile = float(percentile),
        figure = out)

def longitude_diag(reader,event,a,outdir):
    path     = reader._daily_file_map()[a.year]
    sic      = reader._load_local_sic_file(path)
    pre0     = event["start"] - pd.Timedelta(days = a.composite_days-1)
    pre1     = event["start"]
    post0    = event["end"]
    post1    = event["end"] + pd.Timedelta(days = a.composite_days-1)
    pre      = sic.sel(time = slice(pre0,pre1)).mean("time", skipna = True)
    post     = sic.sel(time = slice(post0,post1)).mean("time", skipna = True)
    dsic     = post - pre
    area     = reader.open_area()
    lon_name = next(n for n in ("longitude","lon") if n in dsic.coords)
    lat_name = next(n for n in ("latitude","lat") if n in dsic.coords)
    lon      = dsic[lon_name]
    lat      = dsic[lat_name]
    lon180   = ((lon + 180) % 360) - 180
    dsia     = dsic * area * 1e-12
    bins     = np.arange(-180, 181, 10)
    mids     = .5 * (bins[:-1] + bins[1:])
    sector   = []
    for lo,hi in zip(bins[:-1], bins[1:]):
        sector.append(float(dsia.where((lon180 >= lo) & (lon180 < hi)).sum(skipna = True)))
    sector  = np.asarray(sector)
    plt     = pltmod()
    fig, ax = plt.subplots(2, 1, figsize = (12, 8), gridspec_kw = {"height_ratios": [1.05, 1.0]}, constrained_layout = True)
    # unpack period dates
    pre0, pre1, post0, post1 = pre0, pre1, post0, post1  # if already defined above
    # --- upper panel ---
    sc        = ax[0].scatter(lon.values.ravel(), lat.values.ravel(), c = dsic.values.ravel(), s = 5, cmap = "RdBu_r", vmin = -0.6, vmax = 0.6, lw = 0)
    title_txt = (
        f"NSIDC SIC change: "
        f"{post0:%d %b}–{post1:%d %b %Y} "
        f"minus "
        f"{pre0:%d %b}–{pre1:%d %b %Y}"
    )
    ax[0].set(xlim = (-180, 180), ylim = (-80, -45), xlabel = "Longitude", ylabel = "Latitude", title = title_txt)
    # horizontal colorbar below the top panel
    cbar = fig.colorbar(sc, ax = ax[0], orientation = "horizontal", pad = 0.12, fraction = 0.08, aspect = 35)
    cbar.set_label("ΔSIC")
    # --- lower panel ---
    ax[1].bar(mids, sector, width = 9)
    ax[1].axhline(0, color = "0.3", lw = 0.7)
    ax[1].set(xlim = (-180, 180), xlabel = "Longitude", ylabel = r"ΔSIA by 10° sector (million km$^2$)", title = "Longitude sectors contributing to retreat")
    out = outdir/f"NSIDC_SH_retreat_longitude_{a.year}.png"
    fig.savefig(out, dpi = 200, bbox_inches = "tight", facecolor = "white")
    plt.close(fig)
    worst = np.argsort(sector)[:5]
    return dict(figure = out, worst = [(float(bins[i]),float(bins[i+1]),float(sector[i])) for i in worst], periods = (pre0,pre1,post0,post1))

def open_ocean(root,start,end):
    ff = []
    for y in range(start.year, end.year+1):
        ff += sorted((root/f"{y:04d}").glob("*_CMEMS_0p083_ocean_0-500m.nc"))
    if not ff:
        raise FileNotFoundError(f"No CMEMS ocean files under {root}")
    ds = xr.open_mfdataset([str(x) for x in ff], combine = "by_coords", data_vars = "minimal", coords = "minimal", compat = "override", join = "outer", chunks ={"time":7}, decode_timedelta = False)
    return ds.sel(time = slice(start,end))

def hmean(da):
    lat = "latitude" if "latitude" in da.coords else "lat"
    lon = "longitude" if "longitude" in da.coords else "lon"
    return da.weighted(np.cos(np.deg2rad(da[lat]))).mean((lat,lon),skipna=True)

def section(root,end,year,var,outdir):
    e  = pd.Timestamp(year = year, month = end.month, day = end.day)
    s  = e - pd.Timedelta(days = 90)
    ep = e.replace(year = year-1)
    sp = ep-pd.Timedelta(days = 90)
    d1 = open_ocean(root, s, e)
    d0 = open_ocean(root, sp, ep)
    try:
        a1 = hmean(d1[var]).compute()
        a0 = hmean(d0[var]).compute()
    finally:
        d1.close()
        d0.close()
    dep = next(
        n for n in ("depth", "deptht", "lev")
        if n in a1.dims
    )

    vals = np.r_[
        a0.values.ravel(),
        a1.values.ravel(),
    ]
    vals = vals[np.isfinite(vals)]

    if vals.size == 0:
        raise ValueError(
            f"No finite values available for {var} "
            f"in {year-1}/{year} comparison"
        )

    if var == "thetao":
        cmap = "RdBu_r"
        label = "Potential temperature (°C)"

        lo = float(np.nanpercentile(vals, 2))
        hi = float(np.nanpercentile(vals, 98))
        lim = max(abs(lo), abs(hi))

        vmin = -lim
        vmax = lim

    elif var == "so":
        cmap = "viridis"
        label = "Salinity"

        vmin, vmax = [
            float(x)
            for x in np.nanpercentile(vals, [2, 98])
        ]

    else:
        raise ValueError(
            f"Unsupported section variable: {var!r}"
        )
    plt    = pltmod()
    fig,ax = plt.subplots(1, 2, figsize = (13,5.8), sharey = True)
    mesh   = None
    print(
        f"SECTION {var}: "
        f"dims={a1.dims}, "
        f"depth={dep}, "
        f"range={vmin:.3f}..{vmax:.3f}, "
        f"cmap={cmap}"
    )
    for aa,dd,title in ((ax[0],a0,f"{year-1}: same 91-day window"),(ax[1],a1,f"{year}: same 91-day window")):
        mesh = aa.pcolormesh(pd.DatetimeIndex(dd.time.values), dd[dep].values, dd.transpose(dep,"time").values, shading = "auto", cmap = cmap, vmin = vmin, vmax = vmax)
        aa.invert_yaxis()
        aa.set_title(title)
        aa.set_xlabel("Date")
    ax[0].set_ylabel("Depth (m)")
    fig.colorbar(mesh, ax = ax, label = label, shrink = .9)
    fig.suptitle(f"Circum-Antarctic horizontal mean {label.lower()}")
    out = outdir/f"CMEMS_SH_{var}_0-500m_91day_{year}_vs_{year-1}.png"
    fig.savefig(out, dpi = 200, bbox_inches = "tight", facecolor = "white")
    plt.close(fig)
    return out

def markdown(a,event,lon,temp,salt):
    rel=Path("../figs/sh_sia_retreat_202608")
    sectors="\n".join(f"- {lo:+.0f}° to {hi:+.0f}°: {v:+.3f} million km²" for lo,hi,v in lon["worst"])
    txt=f"""# Southern Hemisphere sea-ice-area retreat — August–September {a.year}

This meeting note investigates the sharp Southern Hemisphere sea-ice-area (SIA) retreat in mid-August {a.year} and the subsequent recovery.

## 1. How unusual was the event?

Using daily NSIDC G02202 V6 SIA, the event is defined as the most negative {a.change_days}-day SIA change between {a.search_start} and {a.search_end}.

- Event interval: **{event['start']:%d %b %Y} to {event['end']:%d %b %Y}**
- {a.change_days}-day SIA change: **{event['change']:+.3f} million km²**
- Rank among annual seasonal minima: **{event['rank']} of {event['n']}**
- Percentile among all seasonal {a.change_days}-day changes: **{event['percentile']:.1f}th percentile** (lower = stronger retreat)

![SIA retreat significance]({(rel/event['figure'].name).as_posix()})

## 2. Where did the retreat occur?

The map compares {a.composite_days}-day means immediately before and after the objectively detected retreat. The lower panel integrates ΔSIA into 10° longitude sectors.

![Longitude diagnostic]({(rel/lon['figure'].name).as_posix()})

Largest negative 10° sector contributions:

{sectors}

## 3. Ocean context: upper 500 m

These sections are area-weighted horizontal Southern Ocean means from CMEMS 1/12° Global Ocean Physics Analysis and Forecast, comparing the latest 91-day window with the same calendar interval one year earlier.

### Potential temperature

![Temperature]({(rel/temp.name).as_posix()})

### Salinity

![Salinity]({(rel/salt.name).as_posix()})

## 4. Next iteration

Weekly ERA5/ERA5T files are staged with daily `t2m`, `d2m`, derived `rh2m`, `msl`, `u10`, `v10`; CMEMS weekly sea-ice files contain `siconc`, `sithick`, `usi`, `vsi`, `sialb`, `siage`, `sisnthick`.

Next diagnostics should test the retreat sectors against wind/MSLP anomalies, ice-drift divergence/convergence, and sector-resolved upper-ocean temperature/salinity to separate dynamic from thermodynamic contributions.
"""
    a.markdown.parent.mkdir(parents=True,exist_ok=True); a.markdown.write_text(txt); return a.markdown

def main():
    a = args()
    a.fig_dir.mkdir(parents = True, exist_ok = True)

    cfg = default_config(
        seaice_root = a.seaice_root,
        climatology_start = a.clim_start,
        climatology_end = a.clim_end,
        chunks = None,
    )

    r = NSIDCReader(
        cfg,
        hemisphere = "SH",
        daily_base = a.nsidc_daily_base,
    )

    daily = r.daily_total_sia_sie()
    latest = pd.Timestamp(daily.time.values[-1])

    # --- NSIDC significance figure ---
    sig_path = (
        a.fig_dir
        / f"NSIDC_SH_SIA_{a.change_days}day_retreat_significance_{a.year}.png"
    )

    if sig_path.exists():
        print("REBUILDING event metadata; figure exists:", sig_path)

    ev = event_significance(
        daily.SIA,
        a,
        a.fig_dir,
    )

    # --- NSIDC longitude diagnostic ---
    lon_path = (
        a.fig_dir
        / f"NSIDC_SH_retreat_longitude_{a.year}.png"
    )

    if lon_path.exists():
        print("REBUILDING longitude metadata; figure exists:", lon_path)

    lo = longitude_diag(
        r,
        ev,
        a,
        a.fig_dir,
    )

    # --- CMEMS temperature section ---
    temp_path = (
        a.fig_dir
        / f"CMEMS_SH_thetao_0-500m_91day_{a.year}_vs_{a.year-1}.png"
    )

    if temp_path.exists():
        print("SKIP existing:", temp_path)
        temp = temp_path
    else:
        temp = section(
            a.ocean_root,
            latest,
            a.year,
            "thetao",
            a.fig_dir,
        )

    # --- CMEMS salinity section ---
    salt_path = (
        a.fig_dir
        / f"CMEMS_SH_so_0-500m_91day_{a.year}_vs_{a.year-1}.png"
    )

    if salt_path.exists():
        print("SKIP existing:", salt_path)
        salt = salt_path
    else:
        salt = section(
            a.ocean_root,
            latest,
            a.year,
            "so",
            a.fig_dir,
        )

    md = markdown(
        a,
        ev,
        lo,
        temp,
        salt,
    )

    print(
        f"Event: {ev['start'].date()} -> {ev['end'].date()}, "
        f"ΔSIA={ev['change']:+.3f} million km2, "
        f"rank {ev['rank']}/{ev['n']}"
    )
    print("Wrote", md)

    return 0

if __name__=="__main__":
    raise SystemExit(main())
