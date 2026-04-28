import os
from datetime import datetime
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


# ==============================
# CONNECTION
# ==============================

@contextmanager
def get_conn():
    conn = psycopg2.connect(
        host=os.getenv("PG_HOST"),
        port=os.getenv("PG_PORT"),
        dbname=os.getenv("PG_DB"),
        user=os.getenv("PG_USER"),
        password=os.getenv("PG_PASSWORD"),
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute(query, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)


def fetch_all(query, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()


def fetch_one(query, params=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()


# ==============================
# LEAD HELPERS
# ==============================

def lead_exists(linkedin_url: str) -> bool:
    row = fetch_one(
        "SELECT 1 FROM lead_full_stats WHERE linkedin_url = %s LIMIT 1",
        (linkedin_url,)
    )
    return row is not None


def insert_new_lead(
    lead_id: str,
    linkedin_url: str,
    product_name: str = None,
    product_url: str = None,
):
    """
    Insert new lead safely.
    Product fields are OPTIONAL and backward-compatible.
    """
    execute(
        """
        INSERT INTO lead_full_stats (
            lead_id,
            linkedin_url,
            product_name,
            product_url
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (linkedin_url) DO NOTHING
        """,
        (lead_id, linkedin_url, product_name, product_url)
    )


def update_lead(lead_id: str, **fields):
    """
    Generic update helper.
    """
    if not fields:
        return

    fields["last_action_at"] = datetime.utcnow()

    set_clause = ", ".join(f"{k} = %s" for k in fields.keys())
    values = list(fields.values()) + [lead_id]

    execute(
        f"""
        UPDATE lead_full_stats
        SET {set_clause}
        WHERE lead_id = %s
        """,
        values
    )
