# Changelog

## 0.1.0 - initial scaffold

- Added `floes` package layout for observational sea-ice analysis inside `mawsons-chest`.
- Added Gadi-aware product registry and file discovery.
- Added NSIDC CDR monthly SIC reader and total SIA/SIE calculation.
- Added AFIM-style HTTP directory downloader for NSIDC G02202 products.
- Added PyGMT-first monthly plotting helpers.
- Added PBS entry point: `update_mthly_sea_ice_sci_chat_figs.pbs`.
- Added markdown gallery: `docs/mthly_sea_ice_sci_chat_figs.md`.

## 0.1.1 - first Gadi fixes

- Fall back to the latest available month when the requested month is not present in local holdings.
- Fix PyGMT/GMT basemap frame syntax from `WSen` to `WSne`.
- Use processed ERA5 `mean_windspeed` when raw `u10`/`v10` are not present.
- Add broader ORAS5 filename discovery patterns and optional latest-file fallback.
- Disable verbose tracebacks by default in the PBS script (`FLOES_VERBOSE=1` still enables them).
