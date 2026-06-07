from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
import os


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def previous_complete_month(today: date | None = None) -> tuple[int, int]:
    """Return the previous complete calendar month as ``(year, month)``."""
    today = today or date.today()
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


@dataclass(frozen=True)
class FloesConfig:
    """Central configuration for the lightweight observational workflow.

    This class is deliberately small: it replaces the global variables scattered
    through the old NCL/notebook workflow while avoiding the heavier model-run
    abstractions used in ``shuga``.
    """

    project: str = "gv90"
    user: str = os.environ.get("USER", "unknown")
    gadi_base: Path = Path("/g/data/gv90/wrh581")
    local_cache: Path | None = None
    output_root: Path | None = None
    docs_root: Path | None = None
    climatology_start: int = 1979
    climatology_end: int = 2008
    hemisphere: str = "SH"
    latmax_sh: float = -45.0
    sic_threshold: float = 0.15
    chunks: str | dict | int | None = "auto"

    @property
    def root(self) -> Path:
        return _package_root()

    @property
    def cache_root(self) -> Path:
        if self.local_cache is not None:
            return Path(self.local_cache)
        return Path(f"/g/data/{self.project}/{self.user}/floes")

    @property
    def figure_root(self) -> Path:
        if self.output_root is not None:
            return Path(self.output_root)
        return self.root / "figs" / "mthly_sea_ice_sci_chat"

    @property
    def markdown_gallery(self) -> Path:
        if self.docs_root is not None:
            return Path(self.docs_root) / "mthly_sea_ice_sci_chat_figs.md"
        return self.root / "docs" / "mthly_sea_ice_sci_chat_figs.md"

    def with_updates(self, **kwargs) -> "FloesConfig":
        clean = {k: v for k, v in kwargs.items() if v is not None}
        return replace(self, **clean)


def default_config(**kwargs) -> FloesConfig:
    """Construct a :class:`FloesConfig`, applying optional keyword overrides."""
    return FloesConfig().with_updates(**kwargs)
