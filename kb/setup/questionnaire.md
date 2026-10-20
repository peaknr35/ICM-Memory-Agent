# Workspace setup questionnaire (configure the factory once)

Answer these, then put the answers in `_config/config.json`. Claude can do this with you.

1. **Which Gmail accounts?** Short names (`personal`, `work`) → `sources.gmail.accounts`.
   Current: `personal` (peaknr35@gmail.com).
2. **How far back on the first run?** → `sources.gmail.first_run_days` (365).
3. **Exclude anything else from mail?** Gmail search syntax → `sources.gmail.query_extra`
   (default excludes spam, trash, promotions, social). Example: add `-from:noreply@linkedin.com`.
4. **Claude Code sessions folder** → `sources.claude_code.projects_dir` (`~/.claude/projects`).
5. **Add a notes folder?** (Obsidian vault, `E:\notes`, meeting transcripts saved as .txt/.md)
   → set `sources.notes.enabled: true` and add the path to `sources.notes.folders`.
6. **Summaries automatically after the backfill?** → `summarize.auto_summarize`.
7. **Later sources** (ChatGPT export, Notion, git repos): ask Claude to add a connector
   (see `stages/01_ingest/CONTEXT.md` → "Adding a source").
