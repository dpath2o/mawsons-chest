#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
THIS = Path(__file__).resolve()
FLOES_ROOT = THIS.parents[2]
PARENT = FLOES_ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))
from floes.scripts.update_mthly_sea_ice_sci_chat_figs import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
