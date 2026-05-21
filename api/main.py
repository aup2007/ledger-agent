"""
api/main.py — FastAPI surface for the Aqua doc agent.

The API is a thin wrapper. agent.process()/resume_run() already encode the
business logic; this module only:
  - accepts uploads, persists `documents` + `processing_runs`
  - schedules a BackgroundTask that drives the graph
  - reads back run status / trace / queue
  - POSTs reviewer input into the paused interrupt

agent.py has NO dependency on this file — same as Phase C asks for.

Run with:
    uvicorn api.main:app --reload
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import (
    FastAPI, BackgroundTasks, UploadFile, File, HTTPException, Query,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from psycopg2.extras import Json, RealDictCursor

from agent import process, resume_run
from db import get_conn
from storage import save_upload


app = FastAPI(title="Aqua Doc Agent")

# Comma-separated whitelist of allowed origins. Local dev defaults included;
# in Railway, override with ALLOWED_ORIGINS=https://<web-service>.up.railway.app
_default_origins = "http://localhost:3000,http://localhost:5173"
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _default_origins).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# DB helpers (kept local so the API has a clean dependency graph)
# --------------------------------------------------------------------------
def _insert_document_and_run(filename: str, storage_path: str) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (filename, storage_path) "
            "VALUES (%s, %s) RETURNING id",
            (filename, storage_path),
        )
        doc_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO processing_runs (document_id, status) "
            "VALUES (%s, 'queued') RETURNING id",
            (doc_id,),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
    return run_id


def _set_status(run_id: int, status: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE processing_runs SET status=%s WHERE id=%s",
            (status, run_id),
        )
        conn.commit()


def _finalize(run_id: int, outcome: dict):
    paused = outcome.get("paused")
    status = "needs_review" if (paused or outcome.get("escalated")) else "completed"
    finished = "" if paused else ", finished_at=NOW()"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE processing_runs SET status=%s, verdict=%s, record=%s, "
            f"human_request=%s{finished} WHERE id=%s",
            (
                status,
                outcome.get("verdict"),
                Json(outcome.get("record")) if outcome.get("record") else None,
                outcome.get("human_request"),
                run_id,
            ),
        )
        conn.commit()


def _mark_failed(run_id: int, err: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE processing_runs SET status='failed', human_request=%s, "
            "finished_at=NOW() WHERE id=%s",
            (err, run_id),
        )
        conn.commit()


def _fetch_run(run_id: int) -> Optional[dict]:
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, document_id, status, verdict, record, human_request, "
            "started_at, finished_at FROM processing_runs WHERE id=%s",
            (run_id,),
        )
        return cur.fetchone()


# --------------------------------------------------------------------------
# Background worker
# --------------------------------------------------------------------------
def process_document(run_id: int, path: str):
    """Drives the graph for a queued run. Catches any error -> 'failed'."""
    _set_status(run_id, "running")
    try:
        outcome = process(path, run_id=run_id)
    except Exception as e:
        _mark_failed(run_id, str(e))
        return
    _finalize(run_id, outcome)


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
class ReviewBody(BaseModel):
    human_input: dict


@app.post("/documents")
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
):
    raw = await file.read()
    stored_path = save_upload(raw, file.filename or "upload.pdf")
    run_id = _insert_document_and_run(file.filename or "upload.pdf", stored_path)
    background.add_task(process_document, run_id, stored_path)
    return {"run_id": run_id, "status": "queued"}


@app.get("/runs/{run_id}")
def get_run(run_id: int):
    row = _fetch_run(run_id)
    if not row:
        raise HTTPException(404, "run not found")
    return row


@app.get("/runs/{run_id}/document")
def get_document(run_id: int):
    """Stream the source PDF inline so the browser can render it."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT d.filename, d.storage_path FROM documents d "
            "JOIN processing_runs r ON r.document_id = d.id "
            "WHERE r.id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "document not found")
    filename, path = row
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/runs/{run_id}/trace")
def get_trace(run_id: int):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT step_index, node, detail, created_at FROM agent_steps "
            "WHERE run_id=%s ORDER BY step_index",
            (run_id,),
        )
        return cur.fetchall()


@app.get("/runs")
def list_runs(status: Optional[str] = Query(None)):
    sql = ("SELECT id, document_id, status, verdict, human_request, started_at "
           "FROM processing_runs")
    params: tuple = ()
    if status:
        sql += " WHERE status=%s"
        params = (status,)
    sql += " ORDER BY started_at DESC LIMIT 100"
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@app.post("/runs/{run_id}/review")
def review_run(run_id: int, body: ReviewBody):
    row = _fetch_run(run_id)
    if not row:
        raise HTTPException(404, "run not found")
    if row["status"] != "needs_review":
        raise HTTPException(
            409, f"run not in needs_review (status={row['status']})")
    try:
        outcome = resume_run(run_id, body.human_input)
    except Exception as e:
        _mark_failed(run_id, str(e))
        raise HTTPException(500, str(e))
    _finalize(run_id, outcome)
    return _fetch_run(run_id)
