from __future__ import annotations
from pathlib import Path
import glob
import xarray as xr
from .registry import DataProduct, get_product

def find_product_files(product: str | DataProduct, *, base: str | Path, strict: bool = False) -> list[Path]:
    prod = get_product(product) if isinstance(product, str) else product
    base = Path(base)
    matches: list[Path] = []
    for pattern in prod.expand_patterns(base):
        matches.extend(Path(p) for p in glob.glob(pattern, recursive=True))
    matches = sorted(set(matches))
    if strict and not matches:
        raise FileNotFoundError(f"No files found for product={prod.key!r} under base={base}. Patterns: {prod.local_patterns}")
    return matches

def open_product(product: str | DataProduct, *, base: str | Path, chunks = "auto", strict: bool = True, **kwargs) -> xr.Dataset:
    prod = get_product(product) if isinstance(product, str) else product
    files = find_product_files(prod, base=base, strict=strict)
    if not files:
        return xr.Dataset(attrs={"warning": f"No files found for {prod.key}"})
    return xr.open_mfdataset([str(f) for f in files],
                             chunks           = chunks,
                             parallel         = False,
                             data_vars        = "minimal",
                             coords           = "minimal",
                             compat           = "override",
                             join             = "outer",
                             combine          = "by_coords",
                             decode_timedelta = False, **kwargs)

def first_existing(product: str | DataProduct, *, base: str | Path) -> Path | None:
    files = find_product_files(product, base=base, strict=False)
    return files[0] if files else None
