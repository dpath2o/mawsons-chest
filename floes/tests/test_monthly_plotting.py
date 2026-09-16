from __future__ import annotations

from pathlib import Path

import pandas as pd
import xarray as xr
from floes.config import default_config
from floes.plotting.monthly import MonthlySeaIceChatPlotter


class _FakeFigure:
    def __init__(self) -> None:
        self.frame: list[str] | None = None

    def basemap(self, **kwargs) -> None:
        self.frame = kwargs["frame"]

    def plot(self, **kwargs) -> None:
        return None

    def legend(self, **kwargs) -> None:
        return None

    def savefig(self, path: str, **kwargs) -> None:
        Path(path).touch()


def test_total_sia_sie_uses_portable_default_frame_axes(tmp_path: Path) -> None:
    time = pd.date_range("2025-01-01", periods=3, freq="MS")
    data = xr.Dataset(
        {"SIA": ("time", [5.0, 6.0, 7.0]), "SIE": ("time", [6.0, 7.0, 8.0])},
        coords={"time": time},
    )
    figure = _FakeFigure()
    plotter = MonthlySeaIceChatPlotter(default_config())
    plotter._figure = lambda: (object(), figure)

    plotter.plot_total_sia_sie(data, output=tmp_path / "sia_sie.png")

    assert figure.frame is not None
    assert not any(item in {"WSne", "WSen"} for item in figure.frame)
