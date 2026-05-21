"""
seed.py — load the fabricated funds reference into Neon.

Run once after creating the funds_reference table:
    python seed.py

Idempotent: clears the table then re-inserts from schemas.FUNDS_REFERENCE,
so the DB and the code never drift apart.
"""
import json
from db import get_conn
from schemas import FUNDS_REFERENCE


def seed():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE funds_reference RESTART IDENTITY;")
            for f in FUNDS_REFERENCE:
                cur.execute(
                    """
                    INSERT INTO funds_reference
                        (canonical_name, aliases, minimum_investment, currency)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        f["canonical_name"],
                        json.dumps(f["aliases"]),
                        f["minimum_investment"],
                        f["currency"],
                    ),
                )
        conn.commit()
    print(f"seeded {len(FUNDS_REFERENCE)} funds into Neon")


def verify():
    """Proves the ingest worked and previews what the agent will load."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT canonical_name, aliases, minimum_investment, currency "
                "FROM funds_reference ORDER BY id;"
            )
            rows = cur.fetchall()
    print(f"\n{len(rows)} rows in funds_reference:")
    for name, aliases, minimum, ccy in rows:
        print(f"  - {name}  | min {minimum} {ccy} | aliases={aliases}")


if __name__ == "__main__":
    seed()
    verify()