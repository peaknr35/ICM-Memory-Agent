# Knowledge Base Starter

A personal / small-company knowledge base you can stand up in an afternoon,
modeled on Cerebras's internal system
(https://www.cerebras.ai/blog/how-we-built-our-knowledge-base), sized for a
single machine.

**Sources:** Slack · Gmail · GitHub · YouTube — each a small connector
emitting rows in one shared shape.

**Storage:** one SQLite table (`docs`). FTS5 full-text index for exact tokens,
OpenAI embeddings for paraphrase. Slack threads are distilled by a small LLM
into structured question/summary/resolution artifacts before embedding.

**Retrieval:** BM25 + vector cosine, fused with Reciprocal Rank Fusion (k=60),
plus a mild age-decay factor so newer docs win ties. `ask` feeds the top hits
to Claude for an answer with inline citations.

## Setup (the easy way)

Drag this folder into your workspace, open Claude Code in it, and say:

> set up my knowledge base

Claude will interview you about what you want indexed, walk you through the
API keys and tokens, write your `config.json`, run the first ingestion, and
demo a search over your own data. Full instructions it follows are in
`CLAUDE.md`.

## Setup (manual)

1. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
2. `cp .env.example .env` and fill in keys; `cp config.example.json config.json` and edit.
3. Gmail only: OAuth client JSON → `secrets/credentials.json`, then
   `python gmail_auth.py <account>` per account.
4. `set -a && source .env && set +a && python ingest.py`
5. `python kb.py search "anything"` · `python kb.py ask "a question"` · `python kb.py stats`

## Files

    store.py        storage, embeddings, hybrid search
    ingest.py       runs connectors, upserts, embeds (idempotent — cron it)
    kb.py           CLI: search / ask / stats
    connectors/     slack.py, gmail.py, github.py, youtube.py
    gmail_auth.py   one-time Gmail OAuth per account
    config.py       config.json loader
    CLAUDE.md       instructions Claude follows to initialize + operate this

Nothing in here phones home; your data stays in `kb.sqlite` on your machine.
