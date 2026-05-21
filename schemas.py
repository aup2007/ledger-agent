from __future__ import annotations

"""
schemas.py — the contract everything is written against.

Two document schemas (subscription agreement, capital call notice) and the
fabricated funds reference table that validation + lookup depend on.

Design notes for the interview:
- These are the *standardized* records. Extraction targets them; validation
  runs against them; the IGO/NIGO verdict is computed from validation errors.
- `confidence` is carried per-field separately (not in the schema) so the
  schema stays a clean data contract.
"""

"""
| # | File Name | Document Type | Scenario Description | Expected State |
|---|---|---|---|---|
| 1 | sub_clean_a | Subscription | Happy path, layout A | IGO |
| 2 | sub_clean_b | Subscription | Happy path, different layout (proves generalization) | IGO |
| 3 | call_clean_a | Capital call | Happy path, format A | IGO |
| 4 | call_clean_b | Capital call | Happy path, different format | IGO |
| 5 | sub_abbrev_fund | Subscription | Fund name is an alias (TCP III) → agent calls lookup, auto-fixes | NIGO → IGO |
| 6 | call_messy_date_currency | Capital call | Euro number format + $ not USD → agent normalizes, auto-fixes | NIGO → IGO |
| 7 | sub_missing_sig | Subscription | Signature block empty → not auto-fixable → escalate to human | NIGO |
| 8 | call_ambiguous_amount | Capital call | Two conflicting amounts → agent must refuse to guess, escalate | NIGO |

"""




from enum import Enum
from typing import Optional, Union
from pydantic import BaseModel, Field

# Monetary fields accept either the raw verbatim string from the document
# (e.g. "$30,000.00", "US$ 25.000,00") or an already-numeric value. The
# extractor passes the substring through unchanged; normalize_amount() in
# agent.py converts it to float deterministically downstream. Without the
# Union the LLM sees a `float` annotation and refuses to honor the
# "return verbatim" instruction, defaulting to null.
Money = Optional[Union[str, float]]


class DocType(str, Enum):
    subscription = "subscription_agreement"
    capital_call = "capital_call_notice"
    unknown = "unknown"


class InvestorType(str, Enum):
    individual = "individual"
    entity = "entity"


class SubscriptionAgreement(BaseModel):
    """Standardized record for a subscription agreement."""
    investor_legal_name: Optional[str] = Field(None, description="Full legal name of subscriber")
    investor_type: Optional[InvestorType] = None
    fund_name: Optional[str] = Field(None, description="Fund name exactly as written on the document")
    commitment_amount: Money = Field(None, description="Capital commitment — return VERBATIM as written (e.g. \"$30,000.00\")")
    currency: Optional[str] = Field(None, description="ISO currency code if determinable")
    accreditation_basis: Optional[str] = None
    subscription_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD if determinable")
    signature_present: Optional[bool] = None
    tax_id_present: Optional[bool] = None


class CapitalCallNotice(BaseModel):
    """Standardized record for a capital call notice."""
    fund_name: Optional[str] = Field(None, description="Fund name exactly as written on the document")
    investor_name: Optional[str] = None
    call_number: Optional[int] = None
    call_amount: Money = Field(None, description="Amount called — return VERBATIM as written")
    currency: Optional[str] = Field(None, description="ISO currency code if determinable")
    due_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD if determinable")
    remaining_commitment_after_call: Money = Field(None, description="Remaining commitment — return VERBATIM as written")
    wire_instructions_present: Optional[bool] = None
    # Set by the extractor when the document itself is internally contradictory
    # (e.g. two different call amounts). Drives the ambiguity escalation path.
    amount_ambiguous: Optional[bool] = Field(
        False, description="True if the document states conflicting amounts"
    )


SCHEMA_FOR = {
    DocType.subscription: SubscriptionAgreement,
    DocType.capital_call: CapitalCallNotice,
}


# --- Fabricated funds reference (seed into Neon next) ----------------------
# canonical_name, aliases, minimum_investment, currency
FUNDS_REFERENCE = [
    {
        "canonical_name": "Thamesville Capital Partners III, L.P.",
        "aliases": ["Thamesville III", "Thamesville Capital III", "TCP III"],
        "minimum_investment": 25000,
        "currency": "USD",
    },
    {
        "canonical_name": "Aqua Alpha Opportunities Fund, L.P.",
        "aliases": ["Aqua Alpha", "Alpha Fund", "AAOF"],
        "minimum_investment": 50000,
        "currency": "USD",
    },
    {
        "canonical_name": "Brightwater Ventures Fund II, L.P.",
        "aliases": ["Brightwater II", "BW Ventures II"],
        "minimum_investment": 100000,
        "currency": "USD",
    },
    {
        "canonical_name": "Cedar Grove Private Credit Fund, L.P.",
        "aliases": ["Cedar Grove Credit", "CGPC"],
        "minimum_investment": 10000,
        "currency": "USD",
    },
    {
        "canonical_name": "Northwind Real Estate Partners, L.P.",
        "aliases": ["Northwind RE", "NREP"],
        "minimum_investment": 250000,
        "currency": "USD",
    },
]