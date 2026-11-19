import sys
from pathlib import Path

import pytest

from browser_support import chromium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="module")
def browser():
    with chromium() as instance:
        yield instance
