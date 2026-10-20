# Knowledge Base Starter — Claude setup instructions

This folder is a personal/company knowledge base scaffold: ingestion pipelines
for Slack, Gmail, GitHub, and YouTube feeding one SQLite table with hybrid
search (BM25 + embeddings + RRF + age decay) and cited answers.
Architecture pattern: https://www.cerebras.ai/blog/how-we-built-our-knowledge-base

## If there is no `config.json` in this folder: run INITIALIZATION

The user just dropped this folder into their workspace. Before doing anything
else, interview them and set the system up. Ask in plain conversational text
(a few questions at a time, not a wall of 20), covering:

1. **What do you want in your knowledge base?** Which of the four sources
   apply: Slack workspace? Gmail account(s)? GitHub repos? YouTube channel?
   Anything they name that ISN'T one of these — note it and offer to write a
   custom connector afterward (see "Custom connectors" below).
2. **Per selected source:**
   - Slack: do they have a Slack app / user token (`xoxp-…` or `xoxb-…`)?
     If not, walk them through creating one at https://api.slack.com/apps
     (scopes: `channels:history`, `channels:read`, `groups:history`,
     `groups:read`, `users:read`).
   - Gmail: which accounts (short names like `work`, `personal`)? They need a
     Google Cloud OAuth client (Desktop app) with the Gmail API enabled —
     guide them, save the client JSON to `secrets/credentials.json`, then run
     `python gmail_auth.py <account>` for each account.
   - GitHub: is `gh` installed and logged in (`gh auth status`)? How many
     repos / commits per repo to index?
   - YouTube: channel handle (e.g. `@mkbhd`)? They need a YouTube Data API v3
     key from Google Cloud console.
3. **API keys**: OpenAI key (embeddings, required) and Anthropic key
   (Slack-thread distillation + `ask` synthesis, required). Put them in `.env`
   (copy `.env.example`).
4. **Scope**: how much history? (defaults: 90 days of email, 100 messages per
   Slack channel, 10 repos, 30 videos). Adjust in `config.json`.

Then:
- Write `config.json` (shape in `config.example.json`) with their answers.
- Create a venv and `pip install -r requirements.txt` if needed.
- Run `python ingest.py` one source at a time; fix any auth errors as they
  come up (don't make the user debug).
- Verify with `python kb.py stats` and a couple of `python kb.py search`
  queries about things you'd expect in their data.
- Finish by showing them `python kb.py ask "<question about their own data>"`
  working end to end.

## Normal operation (config.json exists)

- Ingest/refresh: `python ingest.py [slack gmail github youtube]` — idempotent,
  safe to re-run or cron.
- Search: `python kb.py search "query" [--source X] [--limit N]`
- Cited answers: `python kb.py ask "question"`
- Counts: `python kb.py stats`
- Env: load `.env` first (`set -a && source .env && set +a`).

## Custom connectors

A connector is any module with `fetch() -> list[dict]` where each dict has
`source, source_id, ts (ISO8601), title, content, metadata`. Drop it in
`connectors/`, register it in the `CONNECTORS` dict in `ingest.py`, and its
rows become searchable alongside everything else — no other changes needed.

## Rules

- Never commit or print token values, `.env` contents, or anything in
  `secrets/` (all gitignored).
- Never delete `kb.sqlite` without asking — it may hold hours of ingestion.
- If a connector breaks, fix the connector; don't hand-edit the database.
