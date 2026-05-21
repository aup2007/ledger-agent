"""
agent.py — Aqua Doc Agent (router architecture)

Graph shape:

    ingest ─► classify ─►(conditional edge on doc_type)
                           ├─ extract_subscription ─┐
                           └─ extract_capital_call ─┤
                                                    ▼
                                                 validate
                                                    │
                                            compute_verdict
                                                    │
                                   (conditional: IGO ──► finalize)
                                   (conditional: NIGO ─► remediate)
                                                    │
                          ┌───────── remediate (decide per error) ──────────┐
                          │ auto-fixable ─► auto_fix ─► validate (loop)      │
                          │ not fixable / ambiguous ─► request_human (HALT)  │
                          └──────────────────────────────────────────────────┘

Design decisions (interview-facing):
- classify  = ONE Groq structured call. Not an agent — a node.
- routing   = a conditional edge. Not a supervisor.
- validate + compute_verdict = pure Python. Financial correctness must NOT
  ride on a probabilistic model.
- remediate = the genuine agentic surface: reason about WHY it failed,
  decide auto-fix vs escalate, loop with a fix_attempts ceiling.
- lookup_reference loads funds_reference from Neon ONCE into memory.
  Live-query swap = make _load_funds() query per call (see note there).

Run from terminal:
    python run.py docs/01_sub_clean_a.pdf
    python run.py --eval
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional, Literal, Any, TypedDict

import fitz  # PyMuPDF
from pydantic import BaseModel
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import interrupt, Command
from langchain_groq import ChatGroq
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from schemas import (
    DocType, SubscriptionAgreement, CapitalCallNotice, SCHEMA_FOR,
)
from db import get_conn, DATABASE_URL_DIRECT

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_FIX_ATTEMPTS = 3

_console = Console()

# Minimal palette: only the two outcomes need to stand out.
NODE_STYLES = {
    "request_human": "bold red",
    "finalize":      "bold green",
}
_DEFAULT_NODE_STYLE = "cyan"

_llm = ChatGroq(model=GROQ_MODEL, temperature=0)


# --------------------------------------------------------------------------
# Reference data: loaded ONCE from Neon into memory.
# --------------------------------------------------------------------------
_FUNDS_CACHE: Optional[list[dict]] = None


def _load_funds() -> list[dict]:
    """
    IN-MEMORY: query Neon once, cache for the process lifetime.

    LIVE-QUERY SWAP: delete the global/cache check and just run the SELECT
    every call (data source changes here only; lookup_reference and every
    agent node stay byte-for-byte identical). Production answer is a TTL
    cache in this same function rather than either extreme.
    """
    global _FUNDS_CACHE
    if _FUNDS_CACHE is None:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT canonical_name, aliases, minimum_investment, currency "
                "FROM funds_reference"
            )
            _FUNDS_CACHE = [
                {
                    "canonical_name": r[0],
                    "aliases": r[1] if isinstance(r[1], list) else json.loads(r[1]),
                    "minimum_investment": float(r[2]),
                    "currency": r[3],
                }
                for r in cur.fetchall()
            ]
    return _FUNDS_CACHE


def lookup_reference(name: Optional[str]) -> Optional[dict]:
    """Resolve a fund name (canonical or alias, case-insensitive)."""
    if not name:
        return None
    n = name.strip().lower()
    for f in _load_funds():
        if n == f["canonical_name"].strip().lower():
            return f
        for a in f["aliases"]:
            if n == a.strip().lower():
                return f
    return None


# --------------------------------------------------------------------------
# Deterministic helpers (no LLM): normalization, validation, verdict.
# --------------------------------------------------------------------------
def normalize_amount(raw: Any) -> Optional[float]:
    """Handle '$50,000.00', 'US$ 25.000,00' (EU), 'USD 75,000', 75000."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw)
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    # European format: '25.000,00' -> dots are thousands, comma is decimal
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1 and len(s.split(",")[-1]) == 2 and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_currency(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    r = raw.strip().upper()
    if r in ("$", "US$", "USD"):
        return "USD"
    return r if len(r) == 3 else None


class ValidationError(BaseModel):
    field: str
    message: str
    auto_fixable: bool


def validate(record: dict, doc_type: DocType) -> list[ValidationError]:
    """Pure-Python schema + business rules. The correctness backbone."""
    errs: list[ValidationError] = []

    fund_name = record.get("fund_name")
    fund = lookup_reference(fund_name)

    if not fund_name:
        errs.append(ValidationError(field="fund_name",
            message="Fund name missing.", auto_fixable=False))
    elif fund is None:
        errs.append(ValidationError(field="fund_name",
            message=f"Fund '{fund_name}' not found in reference; may be an alias.",
            auto_fixable=True))
    elif fund_name.strip() != fund["canonical_name"]:
        errs.append(ValidationError(field="fund_name",
            message=f"Fund '{fund_name}' is an alias of "
                    f"'{fund['canonical_name']}'; rewrite to canonical.",
            auto_fixable=True))

    if doc_type == DocType.subscription:
        amt = record.get("commitment_amount")
        if amt is None:
            errs.append(ValidationError(field="commitment_amount",
                message="Commitment amount missing.", auto_fixable=False))
        elif fund and amt < fund["minimum_investment"]:
            errs.append(ValidationError(field="commitment_amount",
                message=f"Commitment {amt} below fund minimum "
                        f"{fund['minimum_investment']}.", auto_fixable=False))
        if record.get("signature_present") is not True:
            errs.append(ValidationError(field="signature_present",
                message="Signature not present on document.",
                auto_fixable=False))
        if record.get("tax_id_present") is not True:
            errs.append(ValidationError(field="tax_id_present",
                message="Tax ID not present.", auto_fixable=False))

    elif doc_type == DocType.capital_call:
        if record.get("amount_ambiguous"):
            # Contradiction subsumes missing/exceeds — the figure is
            # unknowable, so further numeric checks would just pile on.
            errs.append(ValidationError(field="call_amount",
                message="Document states conflicting call amounts; "
                        "cannot determine the correct figure.",
                auto_fixable=False))
        else:
            if record.get("call_amount") is None:
                errs.append(ValidationError(field="call_amount",
                    message="Call amount missing.", auto_fixable=False))
            rem = record.get("remaining_commitment_after_call")
            amt = record.get("call_amount")
            if rem is not None and amt is not None and amt > rem + amt + 1e-6:
                errs.append(ValidationError(field="call_amount",
                    message="Call amount exceeds remaining commitment.",
                    auto_fixable=False))
        if not record.get("currency"):
            errs.append(ValidationError(field="currency",
                message="Currency missing or unnormalized.",
                auto_fixable=True))
        if record.get("wire_instructions_present") is not True:
            errs.append(ValidationError(field="wire_instructions_present",
                message="Wire instructions not present.", auto_fixable=True))

    return errs


def compute_verdict(errors: list[ValidationError]) -> Literal["IGO", "NIGO"]:
    """Deterministic. NOT an agent decision."""
    return "IGO" if not errors else "NIGO"


# --------------------------------------------------------------------------
# LLM nodes: classify + per-type extract. ONE structured call each.
# --------------------------------------------------------------------------
def _read_pdf(path: str) -> str:
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in doc).strip()
    finally:
        doc.close()


def _groq_json(system: str, user: str) -> dict:
    """One Groq call constrained to JSON. Light on tokens."""
    resp = _llm.invoke([
        ("system", system + " Respond ONLY with a single JSON object, no prose."),
        ("user", user),
    ])
    txt = resp.content.strip()
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    return json.loads(m.group(0) if m else txt)


class AgentState(TypedDict, total=False):
    """LangGraph state schema.

    total=False means every key is optional — nodes populate the state
    progressively as the document moves through the graph, so no single
    node ever sees all keys set. The types document the state contract
    explicitly and give editor/type-checker support, which a bare
    `dict` subclass throws away.
    """
    path: str                       # input PDF path (set by caller)
    raw_text: str                   # extracted text (ingest)
    doc_type: DocType               # classification result (classify)
    classify_confidence: float      # classifier confidence (classify)
    record: dict                    # extracted standardized fields (extract)
    errors: list["ValidationError"] # validation failures (validate)
    verdict: Literal["IGO", "NIGO"] # deterministic verdict (verdict)
    fix_attempts: int               # remediation loop guard
    halted: bool                    # escalation flag (remediate/route)
    human_request: str              # human-readable escalation reason
    trace: list[dict]               # per-node log for the demo
    _to_fix: list["ValidationError"]  # staged fixable errors (remediate->auto_fix)
    run_id: int                     # processing_runs.id — drives persistence
    _step_index: int                # monotonic counter for agent_steps rows


def _log(state: AgentState, node: str, detail: str):
    state.setdefault("trace", []).append({"node": node, "detail": detail})
    style = NODE_STYLES.get(node, _DEFAULT_NODE_STYLE)
    line = Text()
    line.append(f"  {node:<14}", style=style)
    line.append(detail)
    _console.print(line)
    run_id = state.get("run_id")
    if run_id is None:
        return
    idx = state.get("_step_index", 0)
    state["_step_index"] = idx + 1
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_steps (run_id, step_index, node, detail) "
                "VALUES (%s, %s, %s, %s)",
                (run_id, idx, node, detail),
            )
            conn.commit()
    except Exception as e:
        # Tracing must never block the agent. Print and move on.
        print(f"  [_log] WARN: agent_steps insert failed: {e}")


def node_ingest(state: AgentState) -> AgentState:
    state["raw_text"] = _read_pdf(state["path"])
    state["fix_attempts"] = 0
    _log(state, "ingest", f"{len(state['raw_text'])} chars extracted")
    return state


def node_classify(state: AgentState) -> AgentState:
    data = _groq_json(
        "You classify alternative-investment documents.",
        f"Classify this document as exactly one of "
        f"'subscription_agreement' or 'capital_call_notice'. "
        f"Return {{\"doc_type\": ..., \"confidence\": 0-1}}.\n\n"
        f"{state['raw_text'][:2500]}",
    )
    dt = data.get("doc_type", "unknown")
    state["doc_type"] = DocType(dt) if dt in DocType._value2member_map_ \
        else DocType.unknown
    state["classify_confidence"] = float(data.get("confidence", 0))
    _log(state, "classify",
         f"{state['doc_type'].value} (conf={state['classify_confidence']:.2f})")
    return state


def route_after_classify(state: AgentState) -> str:
    if state["classify_confidence"] < 0.55 or state["doc_type"] == DocType.unknown:
        state["halted"] = True
        state["human_request"] = "Document type could not be confidently determined."
        return "request_human"
    return ("extract_subscription"
            if state["doc_type"] == DocType.subscription
            else "extract_capital_call")


def _extract(state: AgentState, schema_cls) -> AgentState:
    fields = json.dumps(schema_cls.model_json_schema()["properties"], indent=0)
    data = _groq_json(
        "You extract structured data from financial documents. "
        "Use null for anything not clearly present. If the document states "
        "two different monetary amounts for the same field, set "
        "\"amount_ambiguous\": true. "
        "CRITICAL: return monetary amounts and currency strings VERBATIM, "
        "character for character, exactly as they appear in the document. "
        "Do not reformat, strip symbols, convert separators, expand "
        "abbreviations, or normalize casing — pass the raw substring "
        "through. Normalization is performed downstream.",
        f"Extract these fields as JSON: {fields}\n\n"
        f"DOCUMENT:\n{state['raw_text'][:3000]}",
    )
    # Deterministic normalization happens OUTSIDE the model.
    # Log raw -> normalized whenever they differ, so the conversion is
    # visible in the trace rather than implied.
    def _norm_amt(field: str):
        if field not in data:
            return
        raw = data.get(field)
        new = normalize_amount(raw)
        data[field] = new
        if raw is not None and str(raw) != str(new):
            _log(state, "normalize", f"{field}: {raw!r} -> {new!r}")

    _norm_amt("commitment_amount")
    _norm_amt("call_amount")
    _norm_amt("remaining_commitment_after_call")
    if "currency" in data:
        raw = data.get("currency")
        new = normalize_currency(raw)
        data["currency"] = new
        if raw is not None and raw != new:
            _log(state, "normalize", f"currency: {raw!r} -> {new!r}")
    state["record"] = data
    _log(state, "extract", json.dumps(data, default=str)[:160])
    return state


def node_extract_subscription(state: AgentState) -> AgentState:
    return _extract(state, SubscriptionAgreement)


def node_extract_capital_call(state: AgentState) -> AgentState:
    return _extract(state, CapitalCallNotice)


def node_validate(state: AgentState) -> AgentState:
    errs = validate(state["record"], state["doc_type"])
    state["errors"] = errs
    _log(state, "validate", f"{len(errs)} error(s): "
         + ", ".join(e.field for e in errs) if errs else "0 errors")
    return state


def node_verdict(state: AgentState) -> AgentState:
    state["verdict"] = compute_verdict(state["errors"])
    _log(state, "verdict", state["verdict"])
    return state


def route_after_verdict(state: AgentState) -> str:
    return "finalize" if state["verdict"] == "IGO" else "remediate"


def node_remediate(state: AgentState) -> AgentState:
    """The agentic surface: reason about WHY it failed, decide path."""
    fixable = [e for e in state["errors"] if e.auto_fixable]
    blocking = [e for e in state["errors"] if not e.auto_fixable]
    if blocking:
        state["halted"] = True
        state["human_request"] = "; ".join(
            f"{e.field}: {e.message}" for e in blocking)
        _log(state, "remediate",
             f"{len(blocking)} non-fixable -> escalate to human")
        return state
    if state["fix_attempts"] >= MAX_FIX_ATTEMPTS:
        state["halted"] = True
        state["human_request"] = "Auto-fix attempts exhausted."
        _log(state, "remediate", "fix ceiling hit -> escalate")
        return state
    state["_to_fix"] = fixable
    _log(state, "remediate",
         f"{len(fixable)} auto-fixable -> attempt fix")
    return state


def route_after_remediate(state: AgentState) -> str:
    return "request_human" if state.get("halted") else "auto_fix"


def node_auto_fix(state: AgentState) -> AgentState:
    state["fix_attempts"] += 1
    rec = state["record"]
    for e in state.get("_to_fix", []):
        if e.field == "fund_name":
            f = lookup_reference(rec.get("fund_name"))
            if f:
                rec["fund_name"] = f["canonical_name"]
                _log(state, "auto_fix",
                     f"resolved fund -> {f['canonical_name']}")
        elif e.field == "currency":
            rec["currency"] = normalize_currency(rec.get("currency")) or "USD"
            _log(state, "auto_fix", "currency normalized")
        elif e.field == "wire_instructions_present":
            # cannot fabricate; mark and let validate re-decide
            _log(state, "auto_fix",
                 "wire instructions cannot be auto-filled (noted)")
    state["record"] = rec
    return state


def node_request_human(state: AgentState) -> AgentState:
    """Durable human-in-the-loop pause.

    `interrupt()` checkpoints the graph and raises GraphInterrupt — the
    invoke returns control to the caller. On resume (`Command(resume=…)`),
    interrupt() returns the supplied payload, we merge it into the record,
    clear halted, and the edge takes us back to `validate` so the loop
    re-evaluates with the operator's input.
    """
    _log(state, "request_human", state.get("human_request", "review needed"))
    human_input = interrupt({
        "reason": state.get("human_request"),
        "record": state.get("record"),
    })
    if human_input:
        state.setdefault("record", {}).update(human_input)
        _log(state, "request_human",
             f"resumed with {json.dumps(human_input, default=str)[:160]}")
    state["halted"] = False
    return state


def node_finalize(state: AgentState) -> AgentState:
    _log(state, "finalize", f"verdict={state['verdict']}")
    return state


def _build_checkpointer() -> Optional[PostgresSaver]:
    """Open a PostgresSaver against the UNPOOLED Neon connection.

    Wraps a psycopg ConnectionPool so dropped connections (Neon idles
    them out) are transparently re-opened. `autocommit=True` and
    `prepare_threshold=0` are required by PostgresSaver.
    """
    if not DATABASE_URL_DIRECT:
        print("WARN: DATABASE_URL_DIRECT not set — running without checkpointer")
        return None
    from psycopg_pool import ConnectionPool
    pool = ConnectionPool(
        DATABASE_URL_DIRECT,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        # Neon's free-tier compute idles connections out; `check` validates
        # each checkout with a cheap SELECT 1 and silently re-opens dead ones.
        check=ConnectionPool.check_connection,
        open=True,
    )
    saver = PostgresSaver(pool)
    saver.setup()
    return saver


_CHECKPOINTER = _build_checkpointer()


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("ingest", node_ingest)
    g.add_node("classify", node_classify)
    g.add_node("extract_subscription", node_extract_subscription)
    g.add_node("extract_capital_call", node_extract_capital_call)
    g.add_node("validate", node_validate)
    g.add_node("verdict", node_verdict)
    g.add_node("remediate", node_remediate)
    g.add_node("auto_fix", node_auto_fix)
    g.add_node("request_human", node_request_human)
    g.add_node("finalize", node_finalize)

    g.set_entry_point("ingest")
    g.add_edge("ingest", "classify")
    g.add_conditional_edges("classify", route_after_classify, {
        "extract_subscription": "extract_subscription",
        "extract_capital_call": "extract_capital_call",
        "request_human": "request_human",
    })
    g.add_edge("extract_subscription", "validate")
    g.add_edge("extract_capital_call", "validate")
    g.add_edge("validate", "verdict")
    g.add_conditional_edges("verdict", route_after_verdict, {
        "finalize": "finalize", "remediate": "remediate",
    })
    g.add_conditional_edges("remediate", route_after_remediate, {
        "auto_fix": "auto_fix", "request_human": "request_human",
    })
    g.add_edge("auto_fix", "validate")     # the remediation loop
    # After interrupt+resume, re-validate so the operator's input is
    # re-evaluated under the same deterministic rules.
    g.add_edge("request_human", "validate")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=_CHECKPOINTER) if _CHECKPOINTER else g.compile()


GRAPH = build_graph()


def _is_interrupted(config: dict) -> bool:
    """True if the graph is paused at an interrupt for this thread."""
    if not _CHECKPOINTER:
        return False
    snapshot = GRAPH.get_state(config)
    return bool(snapshot.next)


def _build_config(run_id: Optional[int]) -> dict:
    config: dict = {"recursion_limit": 25}
    if run_id is not None:
        config["configurable"] = {"thread_id": str(run_id)}
    return config


def process(path: str, run_id: Optional[int] = None) -> dict:
    header = f"[bold]{os.path.basename(path)}[/bold]"
    if run_id is not None:
        header += f"   run_id={run_id}"
    _console.print(Panel(header, expand=False, border_style="cyan"))
    initial: AgentState = {"path": path}
    config = _build_config(run_id)
    if run_id is not None:
        initial["run_id"] = run_id
    final = GRAPH.invoke(initial, config)
    return _summarize(path, final, config)


def _summarize(path: str, final: dict, config: dict) -> dict:
    paused = _is_interrupted(config)
    if paused:
        outcome, style = "NEEDS_REVIEW", "bold yellow"
    elif final.get("halted"):
        # No checkpointer (eval w/o run_id) — fall back to the halted flag.
        outcome, style = "ESCALATED", "bold red"
    else:
        v = final.get("verdict", "?")
        outcome = v
        style = "bold green" if v == "IGO" else "bold red"
    _console.print(Panel(f"RESULT: {outcome}", expand=False, border_style=style))
    return {
        "file": os.path.basename(path),
        "doc_type": (final.get("doc_type").value
                     if hasattr(final.get("doc_type"), "value")
                     else final.get("doc_type") or "unknown"),
        "verdict": final.get("verdict"),
        "escalated": paused or bool(final.get("halted")),
        "paused": paused,
        "human_request": final.get("human_request"),
        "record": final.get("record"),
        "trace": final.get("trace"),
    }


def resume_run(run_id: int, human_input: dict) -> dict:
    """Resume a paused graph with operator-supplied fields.

    Loads the checkpointed thread, hands `human_input` to the waiting
    `interrupt()` call, and lets the graph re-enter `validate`.
    """
    if not _CHECKPOINTER:
        raise RuntimeError("Cannot resume: no checkpointer configured")
    config = _build_config(run_id)
    _console.print(Panel(f"[bold]RESUME run_id={run_id}[/bold]",
                         expand=False, border_style="magenta"))
    final = GRAPH.invoke(Command(resume=human_input), config)
    snapshot = GRAPH.get_state(config)
    # Final state from a resumed graph may be a partial — pull the
    # canonical state from the checkpoint for the summary.
    state = snapshot.values if snapshot else final
    state.setdefault("path", "resumed")
    return _summarize(state.get("path", "resumed"), state, config)