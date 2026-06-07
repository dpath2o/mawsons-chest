from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class DataProduct:
    """Description of a known local/remote data product.

    The registry is intentionally declarative so source paths, variable names,
    and download hints are not duplicated across scripts.
    """

    key: str
    title: str
    local_patterns: tuple[str, ...]
    primary_variable: str | None = None
    lon_name: str | None = None
    lat_name: str | None = None
    time_name: str = "time"
    area_product: str | None = None
    download_family: str | None = None
    notes: str = ""
    attrs: Mapping[str, str] = field(default_factory=dict)

    def expand_patterns(self, base: Path) -> list[str]:
        return [str(base / pat) for pat in self.local_patterns]


KNOWN_PRODUCTS: dict[str, DataProduct] = {
    "nsidc_cdr_sic_monthly_sh": DataProduct(
        key="nsidc_cdr_sic_monthly_sh",
        title="NSIDC CDR monthly sea-ice concentration, Southern Hemisphere",
        local_patterns=(
            "NSIDC/monthly_sic/sic_pss25_*_v*.nc",
            "NSIDC/G02202_V*/south/aggregate/sic_pss25_??????-??????_v*.nc",
        ),
        primary_variable="cdr_seaice_conc_monthly",
        lon_name="longitude",
        lat_name="latitude",
        area_product="nsidc_cell_area_sh",
        download_family="nsidc-g02202",
        notes="Legacy workflow used /g/data/gv90/wrh581/NSIDC/monthly_sic.",
    ),
    "nsidc_cell_area_sh": DataProduct(
        key="nsidc_cell_area_sh",
        title="NSIDC polar stereographic 25 km Southern Hemisphere cell area",
        local_patterns=(
            "NSIDC/NSIDC0771_CellArea_PS_S25km_v1.0.nc",
            "NSIDC/G02202_V*/south/ancillary/*pss25*ancillary*.nc",
        ),
        primary_variable="cell_area",
        notes="Cell area in m2; convert to 10^6 km2 by multiplying by 1e-12.",
    ),
    "osisaf_total_sia": DataProduct(
        key="osisaf_total_sia",
        title="OSI SAF total sea-ice area/extent time series",
        local_patterns=(
            "OSISAF/**/*SIA*.nc",
            "OSI-SAF/**/*SIA*.nc",
            "OSISAF/**/*area*.nc",
        ),
        download_family="osisaf",
        notes="Discovery-only scaffold; exact operational path should be pinned after Gadi inspection.",
    ),
    "oisst_monthly": DataProduct(
        key="oisst_monthly",
        title="NOAA OISST monthly sea-surface temperature",
        local_patterns=(
            "OISST/**/*.nc",
            "OISST/monthly/**/*.nc",
        ),
        primary_variable="sst",
        lon_name="lon",
        lat_name="lat",
        download_family="oisst",
    ),
    "era5_monthly_surface": DataProduct(
        key="era5_monthly_surface",
        title="ERA5 monthly surface fields",
        local_patterns=(
            "ERA5/**/*.nc",
            "ERA5/monthly/**/*.nc",
        ),
        download_family="era5",
        notes="Used for wind/SIE and surface-flux figures; not downloaded by default.",
    ),
    "oras5_thetao_monthly": DataProduct(
        key="oras5_thetao_monthly",
        title="ORAS5 monthly potential temperature",
        local_patterns=("ORAS5/thetao/ORAS5_thetao_monthly_SOcean_*.nc",),
        primary_variable="thetao",
        lon_name="nav_lon",
        lat_name="nav_lat",
        download_family="copernicusmarine",
    ),
    "oras5_vosaline_monthly": DataProduct(
        key="oras5_vosaline_monthly",
        title="ORAS5 monthly salinity",
        local_patterns=("ORAS5/vosaline/ORAS5_vosaline_monthly_SOcean_*.nc",),
        primary_variable="vosaline",
        lon_name="nav_lon",
        lat_name="nav_lat",
        download_family="copernicusmarine",
    ),
}


def get_product(key: str) -> DataProduct:
    try:
        return KNOWN_PRODUCTS[key]
    except KeyError as exc:
        known = ", ".join(sorted(KNOWN_PRODUCTS))
        raise KeyError(f"Unknown data product {key!r}. Known products: {known}") from exc
