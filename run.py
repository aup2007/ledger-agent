"""
run.py — terminal entry point. No FastAPI (added later, per build order).

    python run.py docs/01_sub_clean_a.pdf      # one document, full trace
    python run.py --eval                        # all 8, scored vs expected

Phase A: every run persists a documents row, a processing_runs row, and
one agent_steps row per _log() call. The LangGraph PostgresSaver also
writes its own checkpoint rows to Neon under thread_id=<run_id>.
"""
import os
import sys
import glob
import json
from psycopg2.extras import Json

from agent import process, resume_run, GRAPH
from db import get_conn


def save_workflow_png(path: str = "workflow.png") -> str:
    """Render the LangGraph as a PNG via mermaid.ink. Needs network."""
    png = GRAPH.get_graph().draw_mermaid_png()
    with open(path, "wb") as f:
        f.write(png)
    print(f"wrote {path} ({len(png)} bytes)")
    return path

# Expected outcome per document — this IS the test plan.
EXPECTED = {
    "01_sub_clean_a.pdf":            {"verdict": "IGO",  "escalated": False},
    "02_sub_clean_b.pdf":            {"verdict": "IGO",  "escalated": False},
    "03_call_clean_a.pdf":           {"verdict": "IGO",  "escalated": False},
    "04_call_clean_b.pdf":           {"verdict": "IGO",  "escalated": False},
    "05_sub_abbrev_fund.pdf":        {"verdict": "IGO",  "escalated": False},
    "06_call_messy_date_currency.pdf": {"verdict": "IGO", "escalated": False},
    "07_sub_missing_sig.pdf":        {"verdict": None,   "escalated": True},
    "08_call_ambiguous_amount.pdf":  {"verdict": None,   "escalated": True},
}


def _start_run(path: str) -> int:
    """Insert documents + processing_runs(status='running'). Return run_id."""
    filename = os.path.basename(path)
    abs_path = os.path.abspath(path)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (filename, storage_path) "
            "VALUES (%s, %s) RETURNING id",
            (filename, abs_path),
        )
        doc_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO processing_runs (document_id, status) "
            "VALUES (%s, 'running') RETURNING id",
            (doc_id,),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    return run_id


def _finish_run(run_id: int, outcome: dict):
    """Write status/verdict/record into processing_runs.

    - paused at interrupt -> 'needs_review' (no finished_at)
    - escalated w/o checkpointer -> 'needs_review' (eval path, no resume)
    - otherwise -> 'completed'
    """
    paused = outcome.get("paused")
    if paused or outcome.get("escalated"):
        status = "needs_review"
    else:
        status = "completed"
    finished_clause = "" if paused else ", finished_at=NOW()"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE processing_runs SET status=%s, verdict=%s, record=%s, "
            f"human_request=%s{finished_clause} WHERE id=%s",
            (
                status,
                outcome.get("verdict"),
                Json(outcome.get("record")) if outcome.get("record") else None,
                outcome.get("human_request"),
                run_id,
            ),
        )
        conn.commit()


def _fail_run(run_id: int, err: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE processing_runs SET status='failed', human_request=%s, "
            "finished_at=NOW() WHERE id=%s",
            (err, run_id),
        )
        conn.commit()


def process_persisted(path: str) -> dict:
    """Wrap agent.process() with documents/processing_runs persistence."""
    run_id = _start_run(path)
    try:
        out = process(path, run_id=run_id)
    except Exception as e:
        _fail_run(run_id, str(e))
        raise
    _finish_run(run_id, out)
    out["run_id"] = run_id
    return out


def run_eval():
    files = sorted(glob.glob("docs/*.pdf"))
    rows, passed = [], 0
    for f in files:
        r = process_persisted(f)
        exp = EXPECTED.get(r["file"], {})
        ok = (r["escalated"] == exp.get("escalated")) and (
            exp.get("escalated") or r["verdict"] == exp.get("verdict"))
        passed += ok
        rows.append((r["file"], r["doc_type"], r["verdict"],
                     r["escalated"], "PASS" if ok else "FAIL"))

    print("\n" + "=" * 72)
    print(f"{'FILE':<34}{'TYPE':<14}{'VERDICT':<8}{'ESC':<6}RESULT")
    print("-" * 72)
    for f, dt, v, e, res in rows:
        print(f"{f:<34}{dt:<14}{str(v):<8}{str(e):<6}{res}")
    print("-" * 72)
    print(f"{passed}/{len(files)} passed")
    print("=" * 72)


def resume_persisted(run_id: int, human_input: dict) -> dict:
    """Resume a paused run and write the new status to processing_runs."""
    out = resume_run(run_id, human_input)
    _finish_run(run_id, out)
    out["run_id"] = run_id
    return out


def _parse_resume_args(argv: list[str]) -> tuple[int, dict]:
    # --resume <run_id> --input '<json>'
    try:
        rid = int(argv[argv.index("--resume") + 1])
        payload = json.loads(argv[argv.index("--input") + 1])
    except (ValueError, IndexError) as e:
        raise SystemExit(
            "usage: python run.py --resume <run_id> --input '<json>'") from e
    return rid, payload


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python run.py <pdf>"
              " | python run.py --eval"
              " | python run.py --resume <run_id> --input '<json>'"
              " | python run.py --graph")
    elif sys.argv[1] == "--graph":
        save_workflow_png()
    elif sys.argv[1] == "--eval":
        run_eval()
    elif sys.argv[1] == "--resume":
        rid, payload = _parse_resume_args(sys.argv)
        out = resume_persisted(rid, payload)
        print("\n--- structured result ---")
        print(json.dumps({k: v for k, v in out.items() if k != "trace"},
                         indent=2, default=str))
    else:
        out = process_persisted(sys.argv[1])
        print("\n--- structured result ---")
        print(json.dumps({k: v for k, v in out.items() if k != "trace"},
                         indent=2, default=str))
