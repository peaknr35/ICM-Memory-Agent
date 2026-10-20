"""Stage 02: summaries for long items, written as `segment` and `atom` rows.

    python summarize.py --estimate          # count items + estimated cost, writes stages/02_summarize/output/estimate.md
    python summarize.py --run [--limit N]   # summarize (asks for confirmation unless --yes)

Raw chunks are written at ingest time (stage 01) and are never touched here.
Summaries are pointers back to the raw text, not a replacement for it.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import kbcore
from kbcore import get_state, replace_rows, set_state

OUT = kbcore.STAGES / "02_summarize" / "output"
PROMPT_FILE = kbcore.ROOT / "_config" / "summarize_prompt.md"
EST_OUTPUT_TOKENS = 900  # typical index size per item, used for the estimate only

TOOL = {
    "name": "record_index",
    "description": "Record the search index entries for this document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "segments": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "question": {"type": "string"}, "summary": {"type": "string"}},
                "required": ["title", "question", "summary"]}},
            "atoms": {"type": "array", "items": {"type": "object", "properties": {
                "type": {"type": "string", "enum": ["error_fix", "command", "decision", "path", "fact"]},
                "text": {"type": "string"}}, "required": ["type", "text"]}},
        },
        "required": ["segments", "atoms"],
    },
}


def _mark(row) -> str:
    meta = json.loads(row["metadata"] or "{}")
    return f"{row['ts']}|{meta.get('chars', 0)}"


def pending(db, cfg) -> list:
    """Long items that have no summary yet (or whose content changed since)."""
    idle = timedelta(hours=cfg["summarize"].get("min_idle_hours", 2))
    cutoff = (datetime.now(timezone.utc) - idle).isoformat(timespec="seconds")
    rows = db.execute(
        """SELECT d.* FROM docs d
           WHERE d.kind IN ('email','session','note') AND json_extract(d.metadata,'$.long') = 1
             AND NOT EXISTS (SELECT 1 FROM docs s WHERE s.source=d.source AND s.source_id=d.source_id
                             AND s.kind IN ('segment','atom'))
           ORDER BY d.ts DESC""").fetchall()
    out = []
    for r in rows:
        if r["kind"] == "session" and r["ts"] > cutoff:
            continue  # session probably still running; summarize next time
        if get_state(db, "_summary", f"{r['source']}:{r['source_id']}") == _mark(r):
            continue  # already summarized; it legitimately produced nothing
        out.append(r)
    return out


def full_text(db, row, overlap: int = 200) -> str:
    chunks = db.execute("SELECT content FROM docs WHERE source=? AND source_id=? AND kind='raw' ORDER BY id",
                        (row["source"], row["source_id"])).fetchall()
    parts = [c["content"] for c in chunks]
    return parts[0] + "".join(p[overlap:] for p in parts[1:]) if parts else (row["content"] or "")


def fit(text: str, limit: int) -> str:
    """Keep the start, middle and end when an item is longer than the input budget."""
    if len(text) <= limit:
        return text
    third = limit // 3
    mid = len(text) // 2
    return (text[:third] + "\n\n…[middle of item omitted]…\n\n" + text[mid - third // 2: mid + third // 2]
            + "\n\n…[omitted]…\n\n" + text[-third:])


def estimate(db, cfg) -> dict:
    s = cfg["summarize"]
    items = pending(db, cfg)
    prompt_tokens = len(PROMPT_FILE.read_text(encoding="utf-8")) // 4 + 300
    in_tok = sum(min(int(json.loads(r["metadata"]).get("chars", 0)), s["max_input_chars"]) // 4 + prompt_tokens
                 for r in items)
    out_tok = len(items) * EST_OUTPUT_TOKENS
    cost = in_tok / 1e6 * s["price_per_mtok_input"] + out_tok / 1e6 * s["price_per_mtok_output"]
    by_source = {}
    for r in items:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    est = {"items": len(items), "by_source": by_source, "input_tokens": in_tok, "output_tokens": out_tok,
           "cost_usd": round(cost, 2), "model": s["model"]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "estimate.md").write_text(
        f"# Summary cost estimate ({kbcore.now_iso()})\n\n"
        f"- Items to summarize: **{len(items)}** {by_source}\n"
        f"- Model: `{s['model']}` at ${s['price_per_mtok_input']}/M input, ${s['price_per_mtok_output']}/M output\n"
        f"- Estimated input: {in_tok:,} tokens · output: {out_tok:,} tokens\n"
        f"- **Estimated cost: ${cost:.2f}** (one call per item, prompts kept under 100k tokens)\n\n"
        "Review gate: approve by running `python summarize.py --run`, then set "
        "`summarize.auto_summarize` to true in `_config/config.json` so new items are summarized on each scheduled run.\n",
        encoding="utf-8")
    return est


def _client():
    kbcore.load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY missing from .env")
    import anthropic
    return anthropic.Anthropic()


def summarize_one(client, cfg, row, text: str) -> dict:
    s = cfg["summarize"]
    system = PROMPT_FILE.read_text(encoding="utf-8")
    meta = json.loads(row["metadata"] or "{}")
    header = f"source: {row['source']} · date: {row['ts'][:10]} · title: {row['title']}"
    if meta.get("project"):
        header += f" · project: {meta['project']}"
    msg = client.messages.create(
        model=s["model"], max_tokens=s["max_output_tokens"], system=system,
        tools=[TOOL], tool_choice={"type": "tool", "name": "record_index"},
        messages=[{"role": "user", "content": f"{header}\n\n<document>\n{fit(text, s['max_input_chars'])}\n</document>"}],
    )
    block = next(b for b in msg.content if getattr(b, "type", "") == "tool_use")
    data = block.input if isinstance(block.input, dict) else json.loads(block.input)
    data["_usage"] = (getattr(msg.usage, "input_tokens", 0), getattr(msg.usage, "output_tokens", 0))
    return data


def rows_from_index(row, data) -> list[dict]:
    meta = json.loads(row["metadata"] or "{}")
    pointer = {k: meta[k] for k in ("url", "path", "project", "account", "session_id", "thread_id") if k in meta}
    pointer["parent_title"] = row["title"]
    out = []
    for seg in data.get("segments", [])[:20]:
        out.append(dict(kind="segment", ts=row["ts"], title=seg["title"][:200],
                        content=f"Q: {seg['question']}\n{seg['summary']}", metadata=pointer))
    for atom in data.get("atoms", [])[:60]:
        out.append(dict(kind="atom", ts=row["ts"], title=f"{atom['type']}: {atom['text'][:90]}",
                        content=atom["text"], metadata={**pointer, "atom_type": atom["type"]}))
    return out


def run(db, cfg, limit: int | None = None, log=print) -> dict:
    items = pending(db, cfg)[: (limit or cfg["summarize"].get("max_items_per_run") or 10 ** 9)]
    if not items:
        return {"summarized": 0, "failed": 0}
    client = _client()
    done = failed = tin = tout = 0
    for r in items:
        try:
            data = summarize_one(client, cfg, r, full_text(db, r))
            rows = rows_from_index(r, data)
            replace_rows(db, r["source"], r["source_id"], rows, kinds=kbcore.SUMMARY_KINDS)
            set_state(db, "_summary", f"{r['source']}:{r['source_id']}", _mark(r))
            db.commit()
            tin += data["_usage"][0]
            tout += data["_usage"][1]
            done += 1
        except Exception as e:  # one bad item never stops the batch
            failed += 1
            log(f"  summarize failed for {r['source']}:{r['source_id']}: {type(e).__name__}: {e}")
    s = cfg["summarize"]
    cost = tin / 1e6 * s["price_per_mtok_input"] + tout / 1e6 * s["price_per_mtok_output"]
    rep = {"summarized": done, "failed": failed, "input_tokens": tin, "output_tokens": tout, "cost_usd": round(cost, 3)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "last_run.md").write_text(f"# Last summary run ({kbcore.now_iso()})\n\n```json\n{json.dumps(rep, indent=2)}\n```\n",
                                     encoding="utf-8")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    a = ap.parse_args()
    cfg = kbcore.load_config()
    db = kbcore.connect()
    est = estimate(db, cfg)
    n = min(est["items"], a.limit) if a.limit else est["items"]
    print(f"{est['items']} items need a summary {est['by_source']}. "
          f"Estimated cost for all of them: ${est['cost_usd']:.2f} with {est['model']}.")
    if not a.run:
        print(f"Details: {OUT / 'estimate.md'}")
        return
    if not a.yes and input(f"Summarize {n} items now? [y/N] ").strip().lower() != "y":
        print("Cancelled. Nothing was sent.")
        return
    print(run(db, cfg, a.limit))


if __name__ == "__main__":
    main()
