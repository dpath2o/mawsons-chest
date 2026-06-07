# floes architecture notes

## Why this structure

The legacy `Obs-seaice-analysis` repository was an operational collection of notebooks
and NCL scripts used by experienced operators to update meeting figures. The first-pass
`floes` structure turns that into a small package with four explicit layers:

1. `floes.config` -- one source of truth for Gadi paths, climatology period, output
   locations, hemisphere, and concentration threshold.
2. `floes.io` -- local Gadi discovery plus conservative direct-download helpers.
3. `floes.observations` -- xarray readers and product-specific calculations.
4. `floes.plotting` -- PyGMT-first figure generation and markdown gallery writing.

## Issue-driven design choices

Open issues in the source repository emphasised:

- centralising global variables;
- translating NCL scripts to Python/xarray;
- turning `read_functions.py` into class/module-style readers;
- adding daily sea-ice records later;
- standardising colour scales across figures.

Those are addressed here by the registry/config layer, class-based readers, and shared
plotting palette helpers.

## First-pass limitations

- Some optional products have discovery globs but need exact Gadi paths pinned after a
  live Gadi check.
- The core NSIDC CDR figures are implemented first because they are the most stable and
  most directly represented in the old NCL workflow.
- OISST, ERA5, and ORAS5 hooks are scaffolded but may need variable-name/path adjustment
  against the current `/g/data/gv90/wrh581` holdings.
- PyGMT plotting for curvilinear grids includes a conservative XYZ fallback; this is
  robust but not the final high-performance pathway for every product.
