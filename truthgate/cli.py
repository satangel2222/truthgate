# -*- coding: utf-8 -*-
"""cli.py —— TruthGate CLI entry point."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from installer import main
except ImportError:
    try:
        from truthgate.installer import main
    except ImportError:
        PARENT = HERE.parent
        sys.path.insert(0, str(PARENT))
        from truthgate.installer import main

if __name__ == "__main__":
    main()
