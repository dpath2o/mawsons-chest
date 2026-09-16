# floes

`floes` is a lightweight observational sea-ice analysis package intended to sit beside `shuga` inside `mawsons-chest`. The workflow is intended for the monthly Australian Sea Ice Science Chat:

```bash
cd /path/to/mawsons-chest/floes
qsub ./update_mthly_sea_ice_sci_chat_figs.pbs
```

The PBS job runs `scripts/update_mthly_sea_ice_sci_chat_figs.py`, updates the
NSIDC, University of Bremen and ESA CCI observations by default, discovers the
ERA5/OISST/ocean products available on Gadi, then generates PyGMT-first figures
in:

```text
floes/figs/mthly_sea_ice_sci_chat/
```

and refreshes the markdown gallery at:

```text
floes/docs/mthly_sea_ice_sci_chat_figs.md
```

## Design intent

`floes` is aimed at gridded observations, not model experiments. The package has this layout tree at present:

```text
floes/
  config.py
  io/
  observations/
  plotting/
  scripts/
    downloading/
    observations/
    plotting/
  docs/
  figs/
```

The initial implementation consolidates these legacy/precursor workflows:

- Will Hobbs' `Obs-seaice-analysis` NCL/notebook workflow.
- Dan Atwater's `obs_seaice_analysis` `IceReader`-style refactor.
- AFIM downloader idioms for HTTP directory discovery, retries, manifests, and `.part` files.

## Current figure families

The monthly runner prepares the following products when the required data are present:

1. `NSIDC_SH_sic_anomaly_YYYYMM.png` -- Southern Hemisphere gridded SIC anomaly with climatological and current 15 percent ice-edge overlays.
2. `BREMEN_AMSR2_SH_sic_SIE_YYYYMM.png` -- monthly University of Bremen ASI-AMSR2 SIC, with Bremen and NSIDC 15 percent ice edges.
3. `ESA_CCI_L3C_SH_sit_YYYYMM.png` -- latest available monthly gridded ESA CCI L3C thickness, with the matching NSIDC ice edge.
4. `NSIDC_SH_total_SIA_SIE_monthly.png` -- total sea-ice area and extent monthly time series (generated, but deliberately omitted from the gallery).
5. `OISST_global_sst_anomaly_YYYYMM.png` -- OISST anomaly map with matching Bremen and NSIDC ice edges.
6. `ERA5_wind_SIE_SH_YYYYMM.png` -- Southern Ocean wind speed, monthly MSLP contours and matching Bremen/NSIDC ice edges, using final ERA5 where available and ERA5T for the publication-lag window.
7. `ORAS5_votemper_depth_time_SH_latest.nc` -- current, dynamically complete monthly ocean diagnostic scaffold.
8. `EN4_temperature_depth_time_SH_latest.nc` -- observationally constrained monthly ocean comparison through the latest local EN4 month.

It also reproduces the core NSIDC diagnostics from Will Hobbs' `Obs-seaice-analysis` workflow:

9. `NSIDC_SIA_cdr_monthly_tplot_absolute.png` -- monthly SH SIA anomalies, with positive/negative fill.
10. `NSIDC_SIA_cdr_monthly_tplot_standardised.png` -- the same series normalised by calendar-month standard deviation.
11. `NSIDC_Arctic_vs_Antarctic_annual.png` -- annual global SIE and Arctic-versus-Antarctic comparison.
12. `NSIDC_Arctic_vs_Antarctic_monthly_anomalies.png` -- monthly global and paired hemispheric SIE anomalies.
13. `NSIDC_SIE_cdr_monthly_anoms_byyear.png` -- all SH monthly SIE anomaly cycles with the requested year highlighted.
14. `NSIDC_SIEmax_vs_day-of-max.png` -- five-day-smoothed annual SH maximum SIE versus day of maximum.

The workflow also writes reusable gridded/derived products under
`SeaIce/University_Bremen/AMSR2/asi_daygrid_swath/s6250/processed/`: monthly
SIC and daily SIA/SIE. The daily NSIDC SIA/SIE derived from G02202 is written
beside the figures. These are inputs for the planned 13-week products rather
than gallery figures.

The Will-equivalent diagnostic defaults preserve the original `1979–2018` climatology and `2005` split year. They can be changed independently of the SIC-map climatology:

```bash
python scripts/update_mthly_sea_ice_sci_chat_figs.py \
  --year 2026 \
  --month 8 \
  --will-clim-start 1979 \
  --will-clim-end 2018 \
  --comparison-split-year 2005 \
  --nsidc-daily-base /g/data/jk72/wrh581
```

Use `--skip-will-suite` when only the original map and ancillary products are wanted.

The generated markdown is intentionally curated rather than being a directory
listing. It includes only the latest monthly NSIDC/OISST/ERA5 maps and omits the
supporting total-SIA/SIE, standardised-anomaly and annual hemispheric-comparison
figures even though those files continue to be generated.

The daily reader first derives SIA/SIE from the local gridded G02202 V6 daily
aggregates. It uses `--nsidc-daily-base` and `--gadi-base` only as compatibility
fallbacks for the original pre-integrated files. Where two G02202 aggregates
exist for one year, only the newest ending date/version/revision is opened.
ERA5 surface fields are read directly from `/g/data/rt52`: final
`era5/` is preferred for any complete requested month and near-real-time
`era5t/` fills the current publication lag. Historical climatologies must use
final ERA5 only.

Optional figures are skipped if the local product cannot be found. This is intentional for a first layer: the weekly/monthly operator should get all available figures rather than a failed PBS job because one ancillary product is absent.

## Gadi assumptions

Default Gadi resources are centralised in `floes/config.py` and `floes/io/registry.py`. The current defaults favour this working area:

```text
/g/data/gv90/wrh581
/g/data/gv90/da1339/SeaIce
/g/data/rt52/era5
/g/data/rt52/era5t
```

An override project/user/output directories from the PBS command or the Python script:

```bash
python scripts/update_mthly_sea_ice_sci_chat_figs.py \
  --project gv90 \
  --user da1339 \
  --year 2026 \
  --month 5
```

For a different Gadi data root:

```bash
python scripts/update_mthly_sea_ice_sci_chat_figs.py \
  --gadi-base /g/data/gv90/wrh581 \
  --seaice-root /g/data/gv90/da1339/SeaIce \
  --era5-root /g/data/rt52
```

## Downloading missing data

The PBS job updates observations unless `FLOES_UPDATE_OBSERVATIONS=0` is set.
For a standalone NSIDC refresh:

```bash
python scripts/downloading/download_observations.py nsidc-g02202 \
  --dest-root /g/data/gv90/da1339/SeaIce/NSIDC \
  --start-year 1979 \
  --end-year 2026 \
  --hemis south \
  --monthly aggregate \
  --daily aggregate \
  --ancillary \
  --workers 4
```

The current Bremen AMSR2 month can be refreshed independently:

```bash
python scripts/downloading/download_observations.py bremen-amsr2 \
  --dest-root /g/data/gv90/da1339/SeaIce \
  --year 2026 \
  --months 8 9
```

The ESA CCI updater discovers L2P and L3C files through the official CEDA
THREDDS catalogue. With no year bounds it checks only the newest available year
for each sensor/processing level; give `--start-year` and `--end-year` for a
backfill:

```bash
python scripts/downloading/download_observations.py esa-cci-sit \
  --dest-root /g/data/gv90/da1339/SeaIce \
  --levels L2P L3C \
  --sensors sentinel3a sentinel3b
```

Source catalogues:

- University of Bremen sea-ice archive: <https://seaice.uni-bremen.de/data-archive/>
- ESA Climate Change Initiative data portal: <https://climate.esa.int/en/data/>

>Note: credentials-based services such as Copernicus Marine should be wired through local gadi modules or environment variables rather than hard-coded in the repository.

## Dependencies

The gadi environment required is available via:

```bash
module use /g/data/xp65/public/modules
module load conda/analysis3-26.02
```

>Note: more recent version of analysis3-26.03 and greater have a UNDOCUMENTED issue with PyGMT and NUMPY ... need to report this to environment maintainer ... believe that to be ACCESS-NRI

Otherwise: 

- Python 3.10+
- xarray
- numpy
- pandas
- netCDF4 or h5netcdf
- dask, optional but recommended
- PyGMTv0.15 + GMTv6+ for map products
- matplotlib for the legacy NSIDC time-series and scatter diagnostics

>Note: NCL and cartopy are not required. PyGMT remains the map backend; matplotlib is used for the legacy time-series and scatter diagnostics.

## Integration into mawsons-chest

Recommended first commit:

```bash
cd /path/to/mawsons-chest
git checkout -b add-floes-observations
cp -R /path/to/this/floes ./floes
git add floes
git commit -m "Add floes observational sea-ice analysis scaffold"
```

Then run a dry run on Gadi:

```bash
cd floes
python scripts/update_mthly_sea_ice_sci_chat_figs.py --dry-run --verbose
```
