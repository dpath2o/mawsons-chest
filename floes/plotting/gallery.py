from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class GalleryFigure:
    path: Path
    heading: str
    extra_markdown: str | None = None
    description: str | None = None
    caption: str | None = None


def write_gallery(
    *,
    fig_dir: Path,
    md_path: Path,
    title: str = "Monthly Sea Ice Science Chat Figures",
    figures: Sequence[GalleryFigure] | None = None,
) -> Path:
    """Write the curated monthly gallery in the supplied scientific order."""
    fig_dir = Path(fig_dir)
    md_path = Path(md_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    rel_fig_dir = Path("../figs/mthly_sea_ice_sci_chat")

    if figures is None:
        paths = sorted(
            path for path in fig_dir.glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}
        )
        figures = [GalleryFigure(path=path, heading=path.stem.replace("_", " ")) for path in paths]
    available = [figure for figure in figures if Path(figure.path).exists()]

    lines = [
        f"# {title}",
        "",
        f"Last refreshed: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Figure directory: `{fig_dir}`",
        "",
    ]
    if not available:
        lines.extend(
            [
                "No curated figures were found yet.",
                "",
                "Run:",
                "",
                "```bash",
                "qsub ./update_mthly_sea_ice_sci_chat_figs.pbs",
                "```",
                "",
            ]
        )
    else:
        for figure in available:
            path = Path(figure.path)
            rel = rel_fig_dir / path.name
            lines.extend([f"## {figure.heading}", ""])
            if figure.description:
                lines.extend([figure.description, ""])
            lines.extend([f"![{figure.heading}]({rel.as_posix()})", ""])
            if figure.caption:
                lines.extend([f"*{figure.caption}*", ""])
            if figure.extra_markdown:
                lines.extend([figure.extra_markdown, ""])

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
