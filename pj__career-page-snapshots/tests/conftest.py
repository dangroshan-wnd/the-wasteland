"""Test process configuration established before application imports."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("PREFECT_HOME", str(Path(tempfile.gettempdir()) / "career-page-prefect-test"))
