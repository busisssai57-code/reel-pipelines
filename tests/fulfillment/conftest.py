"""Put the repository root on sys.path for the fulfillment tests.

Scoped to this directory so it composes with any conftest the rest of the
suite defines. `tests/` is deliberately not a package: sibling test modules
import their fixtures as top-level `conftest`, which only resolves while
pytest keeps `tests/` on sys.path.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
