"""Subprocess driver so the CLI can be launched under ``python -I``.

Isolated mode ignores PYTHONPATH and does not add the working directory to
``sys.path``; this driver adds the project root explicitly and delegates to
the real CLI entry point.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from repairjson.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
