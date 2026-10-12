"""Backend readiness check.

    python -m runtime.check          # what is configured (no network calls to paid APIs)
    python -m runtime.check --live   # plus one tiny real call per ready backend

Key values are never printed — only whether they are set.
"""
import os, sys, json, time, importlib.util, urllib.request
from .env import load_env
from .models import make_llm
from .embeddings import make_embedder

KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "VOYAGE_API_KEY")
OFFLINE = ("stub", "hash", "keyword")

def _has(module):
    return importlib.util.find_spec(module) is not None

def _set(name):
    return "set" if os.environ.get(name) else "NOT set"

def _scrub(text):
    for k in KEYS:
        v = os.environ.get(k)
        if v:
            text = text.replace(v, "***")
    return text

def _ollama_models(host):
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=3) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except Exception:
        return None

def status(ollama=True):
    """[(kind, backend, ready, detail)] — never calls a paid API."""
    rows = [("llm", "stub", True, "offline default"),
            ("embed", "hash", True, "offline default (matches shared words, not meaning)"),
            ("embed", "keyword", True, "offline legacy scorer")]
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    have = _ollama_models(host) if ollama else None
    for kind, var, default in (("llm", "OLLAMA_MODEL", "llama3.2"), ("embed", "OLLAMA_EMBED_MODEL", "nomic-embed-text")):
        m = os.getenv(var, default)
        if not ollama:
            rows.append((kind, "ollama", False, "not probed"))
        elif have is None:
            rows.append((kind, "ollama", False, f"no server at {host}"))
        else:
            ok = any(h == m or h.split(":")[0] == m for h in have)
            rows.append((kind, "ollama", ok, f"model {m!r} " + ("available" if ok else f"not pulled (ollama pull {m}, or set {var})")))
    sdk = _has("anthropic")
    cred = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    rows.append(("llm", "claude", sdk and cred,
                 f"SDK {'installed' if sdk else 'missing (pip install anthropic)'}; ANTHROPIC_API_KEY {'set' if cred else 'NOT set'}"))
    g = bool(os.environ.get("GEMINI_API_KEY"))
    rows.append(("llm", "gemini", g, f"GEMINI_API_KEY {_set('GEMINI_API_KEY')}"))
    rows.append(("embed", "gemini", g, f"GEMINI_API_KEY {_set('GEMINI_API_KEY')}"))
    rows.append(("embed", "voyage", bool(os.environ.get("VOYAGE_API_KEY")), f"VOYAGE_API_KEY {_set('VOYAGE_API_KEY')}"))
    st = _has("sentence_transformers")
    rows.append(("embed", "sentence-transformers", st, "installed" if st else "not installed (pip install sentence-transformers)"))
    return rows

def live(rows):
    """One tiny real call per ready, non-offline backend (a fraction of a cent on paid APIs)."""
    out = []
    for kind, name, ready, _ in rows:
        if not ready or name in OFFLINE:
            continue
        t = time.perf_counter()
        try:
            if kind == "llm":
                detail = f"replied {make_llm(name)('connection test', 'reply with the single word ok', [])[:40]!r}"
            else:
                detail = f"returned a vector of {len(make_embedder(name)('connection test'))} dimensions"
            out.append((kind, name, True, f"{detail} in {time.perf_counter() - t:.1f}s"))
        except Exception as e:
            out.append((kind, name, False, _scrub(f"{type(e).__name__}: {str(e)[:240]}")))
    return out

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_env()
    rows = status()
    print("Backend readiness (key values are never printed)")
    for kind, name, ok, detail in rows:
        print(f"  {'ready  ' if ok else 'not yet'}  {kind:5} {name:22} {detail}")
    if "--live" not in argv:
        print("\nRun with --live to make one tiny real call per ready backend.")
        return 0
    print("\nLive check")
    res = live(rows)
    if not res:
        print("  nothing to test: no real backend is ready yet")
        return 1
    for kind, name, ok, detail in res:
        print(f"  {'OK    ' if ok else 'FAILED'}  {kind:5} {name:22} {detail}")
    return 0 if all(r[2] for r in res) else 1

if __name__ == "__main__":
    sys.exit(main())
