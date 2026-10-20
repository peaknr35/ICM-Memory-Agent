# Personal knowledge base (ICM workspace)

Your Gmail, Claude Code sessions and notes in one local SQLite file, searchable by
keyword in milliseconds, so Claude can check what you actually did before it answers.

**Start here:** `setup/README.md` (install) · `CLAUDE.md` (what's where) · `CONTEXT.md` (which stage does what)

```
kb/
├── CLAUDE.md                 Layer 0  identity + folder map + global rules
├── CONTEXT.md                Layer 1  routing: task → stage
├── stages/
│   ├── 01_ingest/            Layer 2  CONTEXT.md contract · output/last_run.md
│   ├── 02_summarize/         Layer 2  CONTEXT.md contract · output/estimate.md (cost gate)
│   ├── 03_search/            Layer 2  CONTEXT.md: how to search and answer
│   └── 04_freshness/         Layer 2  CONTEXT.md: schedule, logs, health checks
├── _config/                  Layer 3  config.json · summarize_prompt.md · safety.md
├── setup/                    Layer 3  README · gmail_oauth.md · claude_code_retention.md · questionnaire.md
├── kbcore.py                 schema, replace_rows, masking, 2FA filter
├── connectors.py             gmail / claude_code / notes (one function each)
├── summarize.py              Haiku → segment + atom rows
├── kb.py                     init · stats · search
├── ingest_all.py             runs everything; logs to logs/ingest.log
├── gmail_auth.py             one-time read-only Gmail login
├── install.py                one-command setup (CLAUDE.md section, retention, schedule)
├── tests/test_kb.py          offline tests (mock Gmail + mock Haiku)
├── kb.sqlite                 your data (created on first run, gitignored)
└── .env / secrets/ / logs/   gitignored
```

## Commands
```
python kb.py search "words" [--after YYYY-MM-DD] [--source gmail|claude_code|notes] [--limit N]
python kb.py stats
python ingest_all.py
python summarize.py --estimate | --run
python tests/test_kb.py
```

## Design
- **Database:** `docs(id, kind, source, source_id, ts, title, content, metadata, superseded_by)`
  + FTS5 over title/content (`porter unicode61`, synced by triggers) + `ingest_state(source, key, watermark)`.
- **Kinds:** `email`/`session`/`note` (the item), `raw` (4,000-char chunks of long items),
  `segment` (topic: title + question + summary), `atom` (exact error+fix, command, decision, path).
- **Search:** OR of quoted words → `bm25()` on summaries and on raw → RRF (k=60, raw×0.5)
  → ×(1+0.3·e^(−age/180)) → superseded ×0.5 → one line per original item.
- No vector database, no embeddings, nothing leaves your machine except Gmail API
  reads and (once approved) Haiku summary calls.
