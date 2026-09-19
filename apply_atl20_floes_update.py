#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import shutil
import time

ROOT = Path.cwd()
UPDATE = ROOT / "floes/scripts/update_mthly_sea_ice_sci_chat_figs.py"
MONTHLY = ROOT / "floes/plotting/monthly.py"

for p in (UPDATE, MONTHLY):
    if not p.exists():
        raise SystemExit(f"ERROR: expected file not found: {p}")

stamp = time.strftime("%Y%m%d_%H%M%S")
for p in (UPDATE, MONTHLY):
    backup = p.with_suffix(p.suffix + f".bak_{stamp}")
    shutil.copy2(p, backup)
    print(f"Backup: {backup}")

u = UPDATE.read_text()
m = MONTHLY.read_text()

def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"ERROR: {label}: expected 1 anchor, found {n}")
    return text.replace(old, new, 1)

# --- imports / construction -------------------------------------------------
if "from floes.observations.icesat2_atl20 import ICESat2ATL20Reader" not in u:
    u = replace_once(
        u,
        "from floes.observations.nsidc import NSIDCReader  # noqa: E402",
        "from floes.observations.icesat2_atl20 import ICESat2ATL20Reader  # noqa: E402\n"
        "from floes.observations.nsidc import NSIDCReader  # noqa: E402",
        "ATL20 import",
    )

if 'atl20 = ICESat2ATL20Reader(cfg, hemisphere="SH")' not in u:
    u = replace_once(
        u,
        "    bremen = BremenSeaIceReader(cfg)\n",
        "    bremen = BremenSeaIceReader(cfg)\n"
        "    atl20 = ICESat2ATL20Reader(cfg, hemisphere=\"SH\")\n",
        "ATL20 construction",
    )

if "atl20_history: dict[tuple[int, int], Path] = {}" not in u:
    u = replace_once(
        u,
        "    bremen_history: dict[tuple[int, int], Path] = {}\n",
        "    bremen_history: dict[tuple[int, int], Path] = {}\n"
        "    atl20_history: dict[tuple[int, int], Path] = {}\n",
        "ATL20 history dict",
    )

# Bremen: NSIDC edge red, Bremen orange.
u = u.replace(
    'ice_edges=[(ice_edge_for(y, m), "1.0p,black"),(da, "1.0p,orange")]',
    'ice_edges=[(ice_edge_for(y, m), "1.0p,red"),(da, "1.0p,orange")]',
)
u = u.replace(
    'ice_edges=[(ice_edge_for(y, m), "1.0p,black"), (da, "1.0p,orange")]',
    'ice_edges=[(ice_edge_for(y, m), "1.0p,red"), (da, "1.0p,orange")]',
)

# --- ATL20 helper functions -------------------------------------------------
if "def atl20_freeboard_map_for(" not in u:
    anchor = re.search(
        r"(?m)^    def esa_cci_sit_map_for\(year: int, month: int, \*, fallback_latest: bool = False\):",
        u,
    )
    if not anchor:
        raise SystemExit("ERROR: cannot find ESA helper anchor")

    block_lines = [
        "    def atl20_freeboard_map_for(year: int, month: int, *, fallback_latest: bool = False):",
        "        da = atl20.month(year=year, month=month, fallback_latest=fallback_latest).compute()",
        "        y, m, exact = _actual_ym(da, args.year, args.month)",
        "        if fallback_latest and not exact:",
        "            print(",
        "                f\"Using latest available ICESat-2 ATL20 month {y:04d}-{m:02d} \"",
        "                f\"for requested {args.year:04d}-{args.month:02d}.\"",
        "            )",
        "        out = cfg.figure_root / f\"ICESat2_ATL20_SH_mean_freeboard_{y:04d}{m:02d}.png\"",
        "        edges = []",
        "        try:",
        "            edges.append((bremen_edge_for(y, m), \"1.2p,orange\"))",
        "        except Exception as exc:  # noqa: BLE001",
        "            print(f\"WARNING: Bremen SIE edge unavailable for ATL20 {y:04d}-{m:02d}: {exc}\")",
        "        return plotter.plot_gridded_anomaly(",
        "            da,",
        "            output=out,",
        "            title=f\"{y:04d}-{m:02d}\",",
        "            cpt=\"cmocean/thermal\",",
        "            value_range=(0.0, 1.0),",
        "            colorbar_label=\"monthly mean freeboard\",",
        "            colorbar_unit=\"m\",",
        "            ice_edges=edges,",
        "            stride=1,",
        "        )",
        "",
        "    def atl20_freeboard_map():",
        "        return atl20_freeboard_map_for(args.year, args.month, fallback_latest=True)",
        "",
        "    def atl20_history_maps():",
        "        main = atl20.month(year=args.year, month=args.month, fallback_latest=True)",
        "        anchor_year, anchor_month, _ = _actual_ym(main, args.year, args.month)",
        "        for offset in range(3):",
        "            for year, month in _previous_months(anchor_year - offset, anchor_month, 3):",
        "                try:",
        "                    atl20_history[(year, month)] = Path(atl20_freeboard_map_for(year, month))",
        "                except Exception as exc:  # noqa: BLE001",
        "                    print(f\"WARNING: ATL20 history map unavailable for {year:04d}-{month:02d}: {exc}\")",
        "        return len(atl20_history)",
        "",
        "    def atl20_freeboard_timeseries():",
        "        series = atl20.monthly_mean_series().compute()",
        "        nc = cfg.figure_root / \"ICESat2_ATL20_SH_monthly_mean_freeboard.nc\"",
        "        series.to_dataset(name=\"freeboard\").to_netcdf(nc)",
        "        out = cfg.figure_root / \"ICESat2_ATL20_SH_monthly_mean_freeboard_timeseries.png\"",
        "        return plotter.plot_freeboard_timeseries(series, output=out)",
        "",
    ]
    block = "\n".join(block_lines) + "\n"
    u = u[:anchor.start()] + block + u[anchor.start():]

# --- run steps ---------------------------------------------------------------
if 'atl20_map_path = _run_step(' not in u:
    esa_line = re.search(r'(?m)^    esa_sit_path = _run_step\("ESA CCI L3C SIT map".*$', u)
    atl_runs = "\n".join([
        '    atl20_map_path = _run_step("ICESat-2 ATL20 monthly mean freeboard map", atl20_freeboard_map, keep_going=True, manifest=manifest, verbose=args.verbose)',
        '    atl20_ts_path = _run_step("ICESat-2 ATL20 monthly mean freeboard time series", atl20_freeboard_timeseries, keep_going=True, manifest=manifest, verbose=args.verbose)',
    ])
    if esa_line:
        u = u[:esa_line.start()] + atl_runs + u[esa_line.end():]
    else:
        bremen_line = re.search(r'(?m)^    bremen_sic_path = _run_step\("University of Bremen AMSR2 SIC/SIE map".*$', u)
        if not bremen_line:
            raise SystemExit("ERROR: cannot find run-step insertion point")
        u = u[:bremen_line.end()] + "\n" + atl_runs + u[bremen_line.end():]

# Replace ESA rolling archive with ATL20 rolling archive if present.
esa_hist = re.compile(
    r'(?ms)^    _run_step\(\n        "ESA CCI rolling map archive",\n        esa_history_maps,\n        keep_going=True,\n        manifest=manifest,\n        verbose=args\.verbose,\n    \)\n'
)
atl_hist = (
    '    _run_step(\n'
    '        "ICESat-2 ATL20 rolling map archive",\n'
    '        atl20_history_maps,\n'
    '        keep_going=True,\n'
    '        manifest=manifest,\n'
    '        verbose=args.verbose,\n'
    '    )\n'
)
if '"ICESat-2 ATL20 rolling map archive"' not in u:
    if esa_hist.search(u):
        u = esa_hist.sub(atl_hist, u, count=1)
    else:
        marker = "    if not args.skip_will_suite:\n"
        u = replace_once(u, marker, atl_hist + "\n" + marker, "ATL20 history run")

# --- gallery -----------------------------------------------------------------
if 'f"ICESat-2 ATL20 SH monthly mean freeboard — ' not in u:
    start = u.find("    if esa_sit_path:")
    if start < 0:
        raise SystemExit("ERROR: cannot find ESA gallery block")
    nxt = re.search(r"(?m)^    if [A-Za-z_][A-Za-z0-9_]*_path:", u[start + 1:])
    if not nxt:
        raise SystemExit("ERROR: cannot find end of ESA gallery block")
    end = start + 1 + nxt.start()
    gallery_lines = [
        "    if atl20_map_path:",
        "        name = Path(atl20_map_path).stem",
        "        stamp = name.rsplit(\"_\", 1)[-1]",
        "        gallery_figures.append(",
        "            GalleryFigure(",
        "                Path(atl20_map_path),",
        "                f\"ICESat-2 ATL20 SH monthly mean freeboard — {stamp[:4]}-{stamp[4:]}\",",
        "                caption=(",
        "                    \"NASA ICESat-2 ATL20 v005 monthly mean sea-ice freeboard on the native 25 km \"",
        "                    \"Southern Hemisphere polar stereographic grid. ATL20 monthly grid-cell means use \"",
        "                    \"all available daily mean freeboards weighted by contributing segment length. \"",
        "                    \"The solid orange contour is the University of Bremen AMSR2 15% SIC sea-ice edge \"",
        "                    \"for the matching month. Freeboard is not sea-ice thickness.\"",
        "                ),",
        "                extra_markdown=_history_table(",
        "                    atl20_history,",
        "                    anchor_year=int(stamp[:4]),",
        "                    anchor_month=int(stamp[4:]),",
        "                    prefix=\"ICESat2_ATL20_SH_mean_freeboard\",",
        "                ),",
        "            )",
        "        )",
        "    if atl20_ts_path:",
        "        gallery_figures.append(",
        "            GalleryFigure(",
        "                Path(atl20_ts_path),",
        "                \"ICESat-2 ATL20 SH monthly mean freeboard time series\",",
        "                caption=(",
        "                    \"Southern Hemisphere spatial mean of valid 25 km ATL20 v005 monthly mean-freeboard \"",
        "                    \"grid cells. The ICESat-2 record begins in October 2018, so this panel shows the \"",
        "                    \"complete available record rather than a full ten years.\"",
        "                ),",
        "            )",
        "        )",
        "",
    ]
    u = u[:start] + "\n".join(gallery_lines) + u[end:]

# Bremen caption text.
u = u.replace(
    "Monthly-mean University of Bremen ASI-AMSR2 SIC at 6.25 km. The black contour is the ",
    "Monthly-mean University of Bremen ASI-AMSR2 SIC at 6.25 km. The red contour is the ",
)

UPDATE.write_text(u)

# --- monthly.py time-series method ------------------------------------------
if "def plot_freeboard_timeseries(" not in m:
    method_lines = [
        "",
        "    def plot_freeboard_timeseries(",
        "        self,",
        "        da: xr.DataArray,",
        "        *,",
        "        output: Path,",
        "        title: str = \"Southern Hemisphere ICESat-2 ATL20 monthly mean freeboard\",",
        "    ) -> Path:",
        "        \"\"\"Plot the complete monthly ATL20 freeboard record.\"\"\"",
        "        pygmt, fig = self._figure()",
        "        output = Path(output)",
        "        output.parent.mkdir(parents=True, exist_ok=True)",
        "        if \"time\" not in da.coords:",
        "            raise ValueError(\"Freeboard DataArray must contain a time coordinate.\")",
        "        series = da.dropna(\"time\")",
        "        if series.size == 0:",
        "            raise ValueError(\"No valid ATL20 monthly mean freeboard values available.\")",
        "        times = pd.to_datetime(series[\"time\"].values)",
        "        x = times.year + (times.month - 0.5) / 12.0",
        "        y = series.values",
        "        xmin, xmax = float(x.min()), float(x.max())",
        "        ymin, ymax = float(y.min()), float(y.max())",
        "        pad_y = max((ymax - ymin) * 0.12, 0.02)",
        "        fig.basemap(",
        "            region=[xmin, xmax, max(0.0, ymin - pad_y), ymax + pad_y],",
        "            projection=\"X18c/8c\",",
        "            frame=[\"xaf+lYear\", \"yaf+lFreeboard (m)\", f\"+t{title}\"],",
        "        )",
        "        fig.plot(x=x, y=y, pen=\"1.4p,black\")",
        "        fig.plot(x=x, y=y, style=\"c0.09c\", fill=\"orange\", pen=\"0.25p,black\")",
        "        fig.savefig(str(output), dpi=200)",
        "        return output",
        "",
    ]
    m = m.rstrip() + "\n" + "\n".join(method_lines)

MONTHLY.write_text(m)

print("Updated:")
print(f"  {UPDATE}")
print(f"  {MONTHLY}")
print("Run py_compile and git diff --check next.")
