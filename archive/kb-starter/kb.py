"""NSM Knowledge Base CLI.

  python kb.py search "query" [--source slack|gmail|github|youtube] [--limit N]
  python kb.py ask "question"        # retrieval + LLM synthesis with citations
  python kb.py stats
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store

SYNTH_MODEL = "claude-sonnet-5"

SYNTH_PROMPT = """You are this team's internal knowledge base. Answer the question using ONLY the evidence below. Cite sources inline like [slack:3] using the bracketed ids. If the evidence doesn't answer it, say so.

Question: {question}

Evidence:
{evidence}"""


def cmd_search(args):
    db = store.connect()
    results = store.search(db, args.query, limit=args.limit, source=args.source)
    for score, row in results:
        meta = json.loads(row["metadata"] or "{}")
        loc = meta.get("channel") or meta.get("account") or meta.get("repo") or meta.get("url") or ""
        print(f"[{row['source']}] {score:.4f}  {(row['ts'] or '')[:10]}  {loc}")
        print(f"  {row['title']}")
        snippet = " ".join((row["content"] or "").split())[:200]
        print(f"  {snippet}\n")


def cmd_ask(args):
    import anthropic

    db = store.connect()
    results = store.search(db, args.query, limit=8)
    evidence = []
    for i, (_, row) in enumerate(results):
        body = " ".join((row["content"] or "").split())[:1500]
        evidence.append(f"[{row['source']}:{i}] ({(row['ts'] or '')[:10]}) {row['title']}\n{body}")
    msg = anthropic.Anthropic().messages.create(
        model=SYNTH_MODEL, max_tokens=1000,
        messages=[{"role": "user", "content": SYNTH_PROMPT.format(question=args.query, evidence="\n\n".join(evidence))}],
    )
    print(next(b.text for b in msg.content if b.type == "text"))
    print("\n--- sources ---")
    for i, (_, row) in enumerate(results):
        print(f"[{row['source']}:{i}] {row['title']}")


def cmd_stats(args):
    db = store.connect()
    for row in store.stats(db):
        print(f"{row['source']:8s} {row['n']:5d} docs  {row['embedded']} embedded  newest {(row['newest'] or '')[:10]}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--source")
    s.add_argument("--limit", type=int, default=10)
    a = sub.add_parser("ask")
    a.add_argument("query")
    sub.add_parser("stats")
    args = p.parse_args()
    {"search": cmd_search, "ask": cmd_ask, "stats": cmd_stats}[args.cmd](args)


if __name__ == "__main__":
    main()
