# Informal agenda — Sea Ice / FLOES meeting

**Date:** 16 June 2026
**Meeting style:** informal discussion / figure walk-through
**Chair/host:** Dan

## 0. Apologies and notices

- Alex Fraseer and Pat Wongpan sends apologies.
- Pat asked us to highlight the upcoming WCRP CMIP Seminar Series 2026 #4:
  - **Date/time:** 24 June 2026, 08:00–09:00 UTC
  - **Talk:** Lettie Roach — *Persistent Antarctic sea ice biases in CMIP6 models in spite of the recent decade-long sharp decline*
  - **Link:** https://wcrp-cmip.org/event/seminar-series-2026-4/

## 1. Quick check-in / previous meeting flow

- Brief catch-up and any updates carried over from previous meetings.
- I suck ... I failed at generating the figures in [Will's repository](https://github.com/willrhobbs/Obs-seaice-analysis/tree/main)
- state of the ice, a few useful figures, current science items

## 2. `floes` repository status — exists, but very much work in progress

- Repository/docs location for now: https://github.com/dpath2o/mawsons-chest/tree/main/floes/docs
- The `floes` repository/documentation space now exists, but it is nowhere near finished.
- Current status:
  - skeleton framework
- Future work:
  - build out comprehensive sea ice observation(ish) dataset ... ???
    - gather a comprehensive list of publiclly available and accessible observational (including remote sensing) and reanalysis datasets
      - separate datasets into modelled/reanalysis from point-observations and remotely sense(d) products
      - gridded from un-gridded
  - create/allocate space on `/g/data/gv90` sub-directory for this dataset to exist (?)
  - revise download scripts in `floes` to download/update dataset repository
  - 'universalise' (:slightly_smiling_face:) [Will's NCL plots](https://github.com/willrhobbs/Obs-seaice-analysis/tree/main) to work off of the above dataset repository (?)
    - I see this still being python backbone but the `subprocess` or `sys` calls to NCL
  - continue to develop PyGMT workflow for `floes` as an alternate figure space as alternate exceptional figure generator 
- Next meeting:
  - Do we want to use `floes/docs` as a lightweight place for meeting notes, figure links, workflow notes, etc.

## 3. Discussion figures — current Antarctic sea-ice context

Use these as prompts rather than polished diagnostics.

### 3.1 Antarctic sea ice extent

- Project page: https://climate-plots.github.io/projects/Antarctic_SIE/
- Figure options:
  - Antarctic sea ice extent by year: https://climate-plots.github.io/assets/img/Ant_SIE_by_year.png
  - Antarctic sea ice extent anomaly: https://climate-plots.github.io/assets/img/Ant_SIE_anom.png
  - Antarctic seasonal anomaly by year: https://climate-plots.github.io/assets/img/Ant_SIE_year_anoms.png
  - Standardised seasonal anomaly by year: https://climate-plots.github.io/assets/img/Ant_SIE_year_anoms_standardised.png
  - Climatology: https://climate-plots.github.io/assets/img/Ant_SIE_climatology.png

Discussion prompts:

- Where is 2026 sitting relative to the post-2016 low-ice regime?
- Does we want a a standard "first figure" for Antarctic SIE?
- Which figure is most useful for a quick update: absolute extent, anomaly, or standardised anomaly?

### 3.2 Atmospheric/ocean context

- Southern Annular Mode: https://climate-plots.github.io/projects/SAM/
- Global SST page: https://climate-plots.github.io/projects/SST/
  - Note: the Climate Plots SST page is currently marked as not being updated because of NOAA server issues.

Discussion prompts:

- Is SAM useful as a regular contextual figure, or only when it is dynamically relevant?
- What should we use for Southern Ocean SST / surface forcing context if the SST page is not updating?

## 4. Recent Scientific Publications:

- Massom et al. (2026), *The influence of ocean waves on Antarctic sea-ice albedo and seasonal melting, and potential coupled physical and biological feedbacks*, **The Cryosphere**, published 9 June 2026. DOI: https://doi.org/10.5194/tc-20-3271-2026
- Goosse et al. (2026), *Interannual variability of the winter sea ice edge in the Southern Ocean tuned by topography and oceanic transport*, **EGUsphere** preprint, discussion started 4 June 2026. DOI: https://doi.org/10.5194/egusphere-2026-1823
- Fraser et al. (2026), *Revealing the Antarctic marginal ice zone with a decade-long wave-in-ice climatology*, **Nature Communications**, published 20 May 2026. DOI: https://doi.org/10.1038/s41467-026-73203-z
- Simpson et al. (2026), *A novel database of Antarctic meteorological extremes over key ice shelves during 1995–2023*, **EGUsphere** preprint, discussion started 1 June 2026. DOI: https://doi.org/10.5194/egusphere-2026-2270
- Narayanan et al. (2026), *Compound drivers of Antarctic sea ice loss and Southern Ocean destratification*, **Science Advances**, published 8 May 2026. DOI: https://doi.org/10.1126/sciadv.aeb0166

## 5. Recent publications in popular media:

- https://www.theguardian.com/world/2026/jun/13/antarcticas-west-coast-missing-an-area-of-sea-ice-the-size-of-france-as-temperatures-peak-20c-above-average?CMP=oth_b-aplnews_d-1

## 6. Open discussion and actions/handover notes for next meeting 


