"""Tiny HTTP helper shared by the demo scripts. Stdlib only, on purpose --
these scripts should run with a bare `python3`, no venv or pip install
needed first.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

MEMORY_URL = os.environ.get("MEMORY_URL", "http://localhost:8085")
ACTION_URL = os.environ.get("ACTION_URL", "http://localhost:8083")
DEMO_USER_ID = os.environ.get("DEMO_USER_ID", "demo-user")


def call(method: str, url: str, payload: Optional[dict] = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"\n{method} {url} failed ({exc.code}):\n{detail}\n", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as exc:
        print(f"\nCould not reach {url}: {exc.reason}", file=sys.stderr)
        print("Is the backend running? Try scripts/demo.sh or scripts/dev.sh first.\n", file=sys.stderr)
        raise SystemExit(1)
