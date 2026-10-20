# Keeping Claude Code sessions longer than 30 days

Claude Code stores every session as a `.jsonl` file under `~/.claude/projects/`
(Windows: `C:\Users\<you>\.claude\projects\`). At startup it deletes sessions older
than `cleanupPeriodDays`, which **defaults to 30**.

The knowledge base copies each session within 6 hours (the schedule), so the text is
safe in `kb.sqlite` even after Claude Code deletes the file. Search results still show
the old path, but the original file may be gone.

To keep the originals longer too, set it in your user settings file
`~/.claude/settings.json` (create it if missing):

```json
{
  "cleanupPeriodDays": 365
}
```

If the file already has other settings, add the line inside the existing `{ }` and
put a comma after the previous line. `python install.py` can do this for you (it
backs up the file first).

Use a large number (365 or 3650) rather than `0`. Users have reported that `0`
can stop sessions being kept at all, instead of keeping them forever.

**Do it before you install on a machine with old sessions:** sessions already
deleted can't be recovered. Run `python ingest_all.py claude_code` right away so
anything from the last 30 days is captured.
