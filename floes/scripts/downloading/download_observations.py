#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import sys
THIS       = Path(__file__).resolve()
FLOES_ROOT = THIS.parents[2]
PARENT     = FLOES_ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))
from floes.io.download import nsidc_cli  # noqa: E402

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download observational products used by floes.")
    sub = p.add_subparsers(dest="product", required=True)
    nsidc = sub.add_parser("nsidc-g02202", help="Download NSIDC NOAA/NSIDC CDR G02202 products")
    # Parse the product command, then pass remaining args to the dedicated parser.
    args, rest = p.parse_known_args(argv)
    if args.product == "nsidc-g02202":
        return nsidc_cli(rest)
    raise ValueError(args.product)

if __name__ == "__main__":
    raise SystemExit(main())
