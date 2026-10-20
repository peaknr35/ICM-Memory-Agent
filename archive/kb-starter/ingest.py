"""Run all connectors, upsert into the shared docs table, embed new rows.

Usage: python ingest.py [slack] [gmail] [github] [youtube]   (no args = all)
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import store
from connectors import github, gmail, slack, youtube

CONNECTORS = {"slack": slack.fetch, "gmail": gmail.fetch, "github": github.fetch, "youtube": youtube.fetch}


def main():
    import config

    enabled = [s for s in config.load().get("sources", list(CONNECTORS)) if s in CONNECTORS]
    targets = [a for a in sys.argv[1:] if a in CONNECTORS] or enabled
    db = store.connect()
    for name in targets:
        print(f"[{name}] ingesting…")
        t0 = time.time()
        try:
            docs = CONNECTORS[name]()
        except Exception as e:
            print(f"[{name}] FAILED: {e}")
            continue
        changed = sum(
            store.upsert(db, d["source"], d["source_id"], d.get("ts"), d.get("title"), d.get("content"), d.get("metadata"))
            for d in docs
        )
        db.commit()
        print(f"[{name}] {len(docs)} docs, {changed} new/updated ({time.time()-t0:.0f}s)")
    print("[embed] vectorizing new docs…")
    n = store.embed_missing(db)
    print(f"[embed] {n} vectors written")
    for row in store.stats(db):
        print(f"  {row['source']:8s} {row['n']:5d} docs  {row['embedded']} embedded  newest {row['newest']}")


if __name__ == "__main__":
    main()
