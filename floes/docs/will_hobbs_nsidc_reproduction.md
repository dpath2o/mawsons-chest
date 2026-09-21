# Will Hobbs NSIDC figure reproduction

The single entry point is:

```bash
python scripts/update_mthly_sea_ice_sci_chat_figs.py --year 2026 --month 8 --verbose
```

The implementation preserves the scientific definitions in `Obs-seaice-analysis` while replacing the NCL and notebook execution paths with Python/xarray calculations.

| Legacy source | Floes output | Definition preserved |
|---|---|---|
| `NSIDC_totalSIA_tplot.ncl`, page 1 | `NSIDC_SIA_cdr_monthly_tplot_absolute.png` | SH monthly SIA anomaly; cyan positive and orange negative fill |
| `NSIDC_totalSIA_tplot.ncl`, page 2 | `NSIDC_SIA_cdr_monthly_tplot_standardised.png` | anomaly divided by each calendar month's sample standard deviation; ±1.96 reference lines |
| `NSIDC_totalSIA_SH-NH_compare.ncl`, page 1 | `NSIDC_Arctic_vs_Antarctic_annual.png` | complete-year mean SIE; global time series and paired hemispheric scatter; 2005 split |
| `NSIDC_totalSIA_SH-NH_compare.ncl`, page 2 | `NSIDC_Arctic_vs_Antarctic_monthly_anomalies.png` | calendar-month SIE anomalies and paired hemispheric scatter |
| `NSIDC_totalSIA_anoms_byyear.ncl` | `NSIDC_SIE_cdr_monthly_anoms_byyear.png` | monthly SH SIE anomaly cycles, with the requested year highlighted |
| `NSIDC_SIE_max_vs_maxdate.ipynb` | `NSIDC_SIEmax_vs_day-of-max.png` | August–October daily SH SIE; centred five-day mean; annual maximum and its day of year |
| `NSIDC_sic_map_generic.ncl` | `NSIDC_SH_sic_anomaly_YYYYMM.png` | monthly SIC anomaly with current and climatological 15% edges |

## Data locations

Monthly NH and SH SIC plus grid-cell areas are discovered below `--gadi-base` (default `/g/data/gv90/wrh581`). The daily maximum diagnostic uses the pre-integrated files below `--nsidc-daily-base` (default `/g/data/jk72/wrh581`):

```text
NSIDC/SIE_daily/NSIDC_SH_totalSIA_daily_*.nc
```

If that location is empty, the reader also searches beneath `--gadi-base`,
including nested directories with similarly named pre-integrated SH daily
SIA/SIE files. It does not silently substitute monthly data for the daily
maximum calculation.

December 1987 and January 1988 are retained on the time axis but masked, matching the legacy workflow's treatment of the known zero-filled gap.

If the latest daily record ends before 31 October, the current year's maximum is explicitly labelled provisional in the figure.

## Gadi smoke test

```bash
module use /g/data/xp65/public/modules
module load conda/analysis3-26.02
cd /path/to/mawsons-chest/floes

python scripts/update_mthly_sea_ice_sci_chat_figs.py \
  --year 2026 \
  --month 8 \
  --gadi-base /g/data/gv90/wrh581 \
  --nsidc-daily-base /g/data/jk72/wrh581 \
  --verbose
```

The runner records missing or failed optional products in the JSON manifest and continues unless `--strict` is supplied.
