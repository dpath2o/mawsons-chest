from __future__ import annotations

from pathlib import Path
from datetime import datetime


def write_gallery(*, fig_dir: Path, md_path: Path, title: str = "Monthly Sea Ice Science Chat Figures") -> Path:
    """Write a markdown gallery containing all PNG/JPG figures in ``fig_dir``."""
    fig_dir = Path(fig_dir)
    md_path = Path(md_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    figures = sorted([p for p in fig_dir.glob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}])

    rel_fig_dir = Path("../figs/mthly_sea_ice_sci_chat")
    lines = [
        f"# {title}",
        "",
        f"Last refreshed: {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Figure directory: `{fig_dir}`",
        "",
    ]
    if not figures:
        lines.extend([
            "No figures were found yet.",
            "",
            "Run:",
            "",
            "```bash",
            "qsub ./update_mthly_sea_ice_sci_chat_figs.pbs",
            "```",
            "",
        ])
    else:
        for fig in figures:
            rel = rel_fig_dir / fig.name
            nice = fig.stem.replace("_", " ")
            lines.extend([f"## {nice}", "", f"![{nice}]({rel.as_posix()})", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
