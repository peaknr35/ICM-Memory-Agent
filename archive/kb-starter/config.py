"""Loads config.json (created during initialization — see CLAUDE.md)."""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"


def load():
    if not CONFIG_PATH.exists():
        raise SystemExit(
            "No config.json found. Open this folder in Claude Code and say "
            "'set up my knowledge base' to run initialization (see CLAUDE.md)."
        )
    return json.loads(CONFIG_PATH.read_text())
