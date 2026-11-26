import os
import sys
from pathlib import Path

import pytest

from browser_support import chromium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _name in ("BPN_EDIT_ALLOWLIST", "BPN_EDIT_ALLOWED_UIDS_DEV", "BPN_EDIT_ALLOWED_UIDS_PROD"):
    os.environ.pop(_name, None)


@pytest.fixture(scope="module")
def browser():
    with chromium() as instance:
        yield instance
