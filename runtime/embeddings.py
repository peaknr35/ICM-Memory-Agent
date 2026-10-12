"""Pluggable embedding backends for vector retrieval in Store.

Each backend is a callable `embed(text) -> list[float]`. `make_embedder(name)`
selects one (env MEMORY_EMBED_BACKEND, default 'hash'). The special name
'keyword' returns the string "keyword", which tells Store to use its legacy
whole-word keyword scorer instead of vectors.

Default 'hash' is pure Python (no deps, no network, deterministic) so tests and
offline use work out of the box. ollama/gemini/voyage/sentence-transformers are
opt-in; real backends resolve keys/clients on first call (matches models.py).

Note: Anthropic has no first-party embeddings API, so there is no 'claude'
backend — use 'voyage' (Voyage AI, Anthropic's recommended embeddings provider).
"""
import os, re, math, hashlib
from .env import load_env
from .models import _post

DIM = 256
_TOK = re.compile(r"[a-z0-9]+")

def _l2(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)

def cosine(a, b):
    """Dot product; inputs are expected L2-normalized, so this is cosine similarity."""
    return sum(x * y for x, y in zip(a, b))

def hash_embed(text, dim=DIM):
    """Deterministic hashing embedder: signed token buckets, L2-normalized. No deps."""
    v = [0.0] * dim
    for tok in _TOK.findall(text.lower()):
        if len(tok) < 2:
            continue
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    return _l2(v)

def ollama_embed(model=None, host=None):
    """Local Ollama embeddings via its HTTP API (no SDK dependency)."""
    model = model or os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    def _embed(text):
        out = _post(f"{host}/api/embeddings", {"model": model, "prompt": text}, {})
        return _l2(out["embedding"])
    return _embed

def gemini_embed(model=None):
    """Google Gemini embeddings (key in header, not URL; resolved on first call)."""
    model = model or os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
    def _embed(text):
        key = os.environ["GEMINI_API_KEY"]
        out = _post(url, {"model": f"models/{model}", "content": {"parts": [{"text": text}]}},
                    {"x-goog-api-key": key})
        return _l2(out["embedding"]["values"])
    return _embed

def voyage_embed(model=None):
    """Voyage AI embeddings — Anthropic's recommended provider (Claude has no embeddings API)."""
    model = model or os.getenv("VOYAGE_MODEL", "voyage-4")
    def _embed(text):
        key = os.environ["VOYAGE_API_KEY"]
        out = _post("https://api.voyageai.com/v1/embeddings", {"model": model, "input": [text]},
                    {"Authorization": f"Bearer {key}"})
        return _l2(out["data"][0]["embedding"])
    return _embed

def sentence_transformers_embed(model=None):
    """Local high-quality embeddings; needs `pip install 'icm-agent[embeddings]'`."""
    model = model or os.getenv("ST_MODEL", "all-MiniLM-L6-v2")
    cache = {}
    def _embed(text):
        if "m" not in cache:
            from sentence_transformers import SentenceTransformer  # lazy, optional dep
            cache["m"] = SentenceTransformer(model)
        return _l2([float(x) for x in cache["m"].encode(text)])
    return _embed

EMBEDDERS = {
    "hash": lambda: hash_embed,
    "ollama": ollama_embed,
    "gemini": gemini_embed,
    "voyage": voyage_embed,
    "sentence-transformers": sentence_transformers_embed,
}

def make_embedder(backend=None):
    """Return an embedder callable, or the string 'keyword' for the legacy scorer."""
    load_env()
    backend = backend or os.getenv("MEMORY_EMBED_BACKEND", "hash")
    if backend == "keyword":
        return "keyword"
    if backend not in EMBEDDERS:
        raise ValueError(f"unknown embedder {backend!r}; choose from {sorted(EMBEDDERS) + ['keyword']}")
    return EMBEDDERS[backend]()
