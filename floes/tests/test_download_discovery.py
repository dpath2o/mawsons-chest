from __future__ import annotations

from pathlib import Path

from floes.io import download


def test_bremen_download_jobs_preserve_archive_layout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        download,
        "list_nc",
        lambda url: [
            "asi-AMSR2-s6250-20260801-v5.4.nc",
            "asi-AMSR2-s6250-20260731-v5.4.nc",
        ],
    )

    jobs = download.build_bremen_amsr2_jobs(dest_root=tmp_path, year=2026, months=[8])

    assert len(jobs) == 1
    assert jobs[0].dest == (
        tmp_path
        / "University_Bremen/AMSR2/asi_daygrid_swath/s6250/netcdf/2026"
        / "asi-AMSR2-s6250-20260801-v5.4.nc"
    )


def test_esa_cci_download_jobs_follow_thredds_file_server(tmp_path: Path, monkeypatch) -> None:
    def links(url: str) -> list[str]:
        if url.endswith("/SH/catalog.html"):
            return ["2024/catalog.html"]
        if "/L2P/" in url and url.endswith("/2024/catalog.html"):
            return ["04/catalog.html"]
        if "/L2P/" in url and url.endswith("/04/catalog.html"):
            return [
                "catalog.html?dataset=esacci%2Fsea_ice%2Fdata%2Fsea_ice_thickness%2FL2P%2Fsentinel3a%2Fv4.0%2FSH%2F2024%2F04%2Fl2p.nc"
            ]
        if "/L3C/" in url and url.endswith("/2024/catalog.html"):
            return [
                "catalog.html?dataset=esacci%2Fsea_ice%2Fdata%2Fsea_ice_thickness%2FL3C%2Fsentinel3a%2Fv4.0%2FSH%2F2024%2Fl3c.nc"
            ]
        return []

    monkeypatch.setattr(download, "list_links", links)
    jobs = download.build_esa_cci_sit_jobs(
        dest_root=tmp_path,
        levels=["L2P", "L3C"],
        sensors=["sentinel3a"],
    )

    assert {job.dest.name for job in jobs} == {"l2p.nc", "l3c.nc"}
    assert all("/thredds/fileServer/esacci/" in job.url for job in jobs)
    assert any(job.dest.parent.name == "04" for job in jobs)
