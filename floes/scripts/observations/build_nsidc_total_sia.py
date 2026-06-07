#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

THIS = Path(__file__).resolve()
FLOES_ROOT = THIS.parents[2]
PARENT = FLOES_ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from floes.config import default_config  # noqa: E402
from floes.observations.nsidc import NSIDCReader  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Build NSIDC total SIA/SIE NetCDF from local monthly SIC files.")
    p.add_argument("--gadi-base", type=Path, default=Path("/g/data/gv90/wrh581"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--project", default="gv90")
    p.add_argument("--user", default=None)
    args = p.parse_args()
    cfg = default_config(project=args.project, user=args.user, gadi_base=args.gadi_base)
    ds = NSIDCReader(cfg).total_sia_sie()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(args.output)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
