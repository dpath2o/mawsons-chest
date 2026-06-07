from __future__ import annotations

from pathlib import Path


DEFAULT_CPTS = {
    "sic_anom": "polar",
    "sic": "oleron",
    "sst_anom": "polar",
    "wind": "turbo",
    "ocean_temp": "thermal",
}


def make_symmetric_cpt(pygmt, *, cmap: str, limit: float, output: Path | None = None, series_step: float | None = None) -> str | None:
    """Create a symmetric GMT CPT and return its path if written."""
    step = series_step or limit / 10.0
    series = [-limit, limit, step]
    if output is None:
        pygmt.makecpt(cmap=cmap, series=series, continuous=True)
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    pygmt.makecpt(cmap=cmap, series=series, continuous=True, output=str(output))
    return str(output)
