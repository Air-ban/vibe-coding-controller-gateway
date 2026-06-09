"""
Compatibility entrypoint.

The maintained FastAPI app lives in src/openremote/api.py. This file keeps the
old `python opencode_api.py` startup path working.
"""

import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(CURRENT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from openremote.api import app  # noqa: E402


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
