"""Load a local `.env` (KEY=VALUE lines) into os.environ for development.

Real environment variables always win; values are never printed or logged.
`.env` is gitignored. Set ICM_NO_DOTENV=1 to disable (the test suite does, so a
developer's `.env` can never switch tests onto a paid backend).
"""
import os

_loaded = False

def load_env(path=None):
    global _loaded
    if _loaded or os.environ.get("ICM_NO_DOTENV"):
        return
    _loaded = True
    root = os.environ.get("ICM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(path or os.path.join(root, ".env"), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
