"""
db.py — Neon connection helper.

Two connection strings live in .env:

- DATABASE_URL         — POOLED. Default for every ordinary query in this
                         project (documents / processing_runs / agent_steps /
                         funds_reference). Used by get_conn() below.
- DATABASE_URL_DIRECT  — UNPOOLED. Required ONLY by the LangGraph
                         PostgresSaver checkpointer in agent.py. The
                         checkpointer opens long-lived transactions that
                         do not play well with PgBouncer-style pooling.
"""
import os
import psycopg2 as psycopg
from contextlib import contextmanager


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_DIRECT = os.environ.get("DATABASE_URL_DIRECT")


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set (put it in .env)")
    conn = psycopg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()
