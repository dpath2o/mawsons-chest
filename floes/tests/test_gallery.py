from __future__ import annotations

from pathlib import Path

from floes.plotting.gallery import GalleryFigure, write_gallery


def test_curated_gallery_preserves_order_and_excludes_unlisted_figures(tmp_path: Path) -> None:
    fig_dir = tmp_path / "figs"
    fig_dir.mkdir()
    first = fig_dir / "first.png"
    second = fig_dir / "second.png"
    excluded = fig_dir / "excluded.png"
    for path in (first, second, excluded):
        path.touch()

    gallery = tmp_path / "docs" / "gallery.md"
    write_gallery(
        fig_dir=fig_dir,
        md_path=gallery,
        figures=[
            GalleryFigure(first, "First science figure"),
            GalleryFigure(
                second,
                "Second science figure",
                description="How to interpret it.",
                caption="How it was constructed.",
            ),
        ],
    )

    text = gallery.read_text(encoding="utf-8")
    assert text.index("First science figure") < text.index("Second science figure")
    assert "How to interpret it." in text
    assert "*How it was constructed.*" in text
    assert "excluded.png" not in text
