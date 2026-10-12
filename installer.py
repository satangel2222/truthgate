# -*- coding: utf-8 -*-
"""TruthGate Root Installer Forwarder."""
import sys
from pathlib import Path

tg_dir = Path(__file__).resolve().parent / "truthgate"
if str(tg_dir) not in sys.path:
    sys.path.insert(0, str(tg_dir))

from installer import main

if __name__ == "__main__":
    main()
