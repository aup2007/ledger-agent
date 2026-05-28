# ledger-agent

An AI agent that reads messy financial documents, pulls out the data that matters, checks it against the rules, and tells you whether the document is good to process or needs fixing. Every decision it makes is logged, so you can see exactly why it landed where it did.

## What this is

Anyone who has worked near fund operations knows the IGO/NIGO grind. A document comes in (a subscription form, a trade confirmation, a statement) and someone has to manually check: is this *In Good Order* (IGO) or *Not In Good Order* (NIGO)? Wrong fund name, a number written in European format, a currency that doesn't match, an alias used instead of the real fund name. Miss one and the whole thing bounces back days later.

I built ledger-agent to do that first pass on its own. You hand it a document, it extracts the structured data, runs it through real validation logic, and returns a verdict you can actually defend. If something's wrong, it tries to fix it a few times before pulling in a human.

The part I cared about most: it never asks an LLM "is this correct?" and trusts the answer. The LLM only does the reading. The correctness checks run in plain, deterministic Python, so the verdict is repeatable and you can point to the exact reason a document passed or failed.

## Demo

<!--
  HOW TO ADD YOUR VIDEO (two options):

  OPTION 1 — Google Drive (clickable thumbnail, opens in a new tab):
    1. In Drive, set the video to "Anyone with the link can view"
    2. Copy the link. It looks like:
         https://drive.google.com/file/d/FILE_ID/view?usp=sharing
    3. Add a screenshot of the app to docs/demo-thumbnail.png
    4. Paste the link into the line below, replacing FILE_ID
  GitHub will NOT play a Drive video inside this page; the thumbnail just links out.

  OPTION 2 — true inline player (Drive can't do this):
    Drag your .mp4 straight into the README editor on github.com.
    GitHub uploads it and gives you a https://github.com/user-attachments/assets/... URL.
    Paste that URL on its own line and it renders a real video player.
-->



A short walkthrough: uploading a document, watching the agent extract and validate it, and the reviewer console showing every step it took.

The demo video (`Aqua_AtharvUdayParab_Demo.mp4`) is in the `DEMO VIDEO` directory.


## How it works

The path a document takes through the system:

1. **Read it.** PyMuPDF extracts the text out of the PDF.
2. **Extract it.** An LLM call, constrained to a strict schema, turns that raw text into structured fields. No free-form output. It either fits the shape I defined or it doesn't count.
3. **Validate it.** This part is all Python. Fund-alias resolution against a reference table, European vs US number formats (1.234,56 vs 1,234.56), currency normalization, and the rest. Deterministic: same input, same verdict, every time.
4. **Fix it, maybe.** If validation fails, the agent gets up to three attempts to auto-correct and re-check. After that it stops and escalates to a human instead of guessing forever.
5. **Record it.** Every step gets written to an agent-steps log, so the run is fully auditable. You can see what it extracted, what it changed, and why it ended on IGO or NIGO.

The agent is built with LangGraph and checkpoints its state to Postgres, so if a run gets interrupted it resumes from where it stopped instead of starting over.

## Tech stack

**Agent & backend**
- Python
- LangGraph for the agent graph and state handling
- FastAPI for the API and background workers
- PyMuPDF for PDF text extraction
- Pydantic for the extraction schemas

**Data**
- Postgres (Neon)
- psycopg with health-checked connection pooling
- LangGraph's PostgresSaver for durable checkpointing

**Frontend**
- React + TypeScript: a reviewer console for browsing documents, the agent's steps, and the final verdict

**Infra**
- Railway for deployment

## Project layout

| Path | What's in it |
|------|--------------|
| `agent.py` | The LangGraph agent: extraction, validation, and the remediation loop |
| `api/` | FastAPI app and background workers |
| `frontend/` | React/TypeScript reviewer console |
| `schemas.py` | Pydantic schemas the extraction must conform to |
| `db.py` | Database connection and pooling |
| `storage.py` | Persistence layer |
| `seed.py` | Seeds the funds reference data |
| `run.py` | Entry point |
| `railway.toml` | Deploy config |

## Running it locally

```bash
git clone https://github.com/aup2007/ledger-agent.git
cd ledger-agent

pip install -r requirements.txt

# set your env vars (see below), then seed the reference data
python seed.py

python run.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

You'll need a Postgres connection string and an LLM API key set in your environment. Keep them in a local `.env` and don't commit them.

## Why I built it this way

The honest reason this exists: I wanted to see whether an agent could do real compliance-style checking without the usual trap of "the model said it's fine, so I guess it's fine." Splitting the work is what makes that possible. The LLM reads; deterministic code judges. That separation is what turns the output into something you'd be willing to put in front of an auditor, and it's the whole idea behind the project.