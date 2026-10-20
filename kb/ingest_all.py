"""Stage 04 entry point: run every enabled connector, then (if approved) summaries.

    python ingest_all.py              # all enabled sources
    python ingest_all.py gmail        # just one

If one connector fails, the error is logged and the others still run.
Log: logs/ingest.log   ·   Per-run report: stages/01_ingest/output/last_run.md
"""
from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from logging.handlers import RotatingFileHandler

import kbcore
from connectors import CONNECTORS


def get_logger():
    kbcore.LOG_DIR.mkdir(exist_ok=True)
    log = logging.getLogger("kb")
    if not log.handlers:
        log.setLevel(logging.INFO)
        fh = RotatingFileHandler(kbcore.LOG_DIR / "ingest.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(sh)
    return log


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    log = get_logger()
    kbcore.load_env()
    cfg = kbcore.load_config()
    db = kbcore.connect()
    enabled = [n for n, c in cfg["sources"].items() if c.get("enabled") and n in CONNECTORS]
    targets = [a for a in argv if a in CONNECTORS] or enabled
    log.info(f"=== ingest start: {', '.join(targets)}")
    results, ok = {}, 0
    for name in targets:
        t0 = time.time()
        try:
            rep = CONNECTORS[name](db, cfg)
            db.commit()
            rep["seconds"] = round(time.time() - t0, 1)
            results[name] = {"ok": True, **rep}
            ok += 1
            log.info(f"[{name}] ok {json.dumps(rep)}")
        except Exception as e:
            db.rollback()
            results[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            log.error(f"[{name}] FAILED {type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
    if ok:
        kbcore.set_state(db, "_meta", "last_ingest", kbcore.now_iso())
        db.commit()

    import summarize
    if cfg["summarize"].get("auto_summarize"):
        try:
            rep = summarize.run(db, cfg, log=log.warning)
            results["_summaries"] = rep
            log.info(f"[summaries] {json.dumps(rep)}")
        except Exception as e:
            results["_summaries"] = {"error": str(e)}
            log.error(f"[summaries] FAILED {type(e).__name__}: {e}")
    else:
        est = summarize.estimate(db, cfg)
        results["_summaries"] = {"auto_summarize": False, "pending": est["items"], "est_cost_usd": est["cost_usd"]}
        if est["items"]:
            log.info(f"[summaries] {est['items']} long items waiting (est. ${est['cost_usd']:.2f}). "
                     "Approve with: python summarize.py --run")

    st = kbcore.stats(db)
    out = kbcore.STAGES / "01_ingest" / "output" / "last_run.md"
    out.write_text(
        f"# Last ingest run ({kbcore.now_iso()})\n\n```json\n{json.dumps(results, indent=2)}\n```\n\n"
        f"Total rows: {st['total']:,} · items per source: {st['items']}\n", encoding="utf-8")
    log.info(f"=== ingest done: {ok}/{len(targets)} connectors ok · {st['total']:,} rows")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
