"""Local SQLite database. Same tables as the design deck (slide 9).

Design fix vs. the deck: customers.date_of_birth is added, because callers
verify with National ID + birth date (slide 15) and the deck schema had no
birth date column.
"""
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> str:
    return os.getenv("AMINA_DB", str(ROOT / "amina.db"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    full_name     TEXT NOT NULL,
    phone         TEXT,
    segment       TEXT,
    joined_at     TEXT,
    national_id   TEXT NOT NULL UNIQUE,
    date_of_birth TEXT NOT NULL
);

CREATE TABLE accounts (
    account_id  INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    type        TEXT,
    currency    TEXT,
    balance     REAL,
    status      TEXT
);

CREATE TABLE cards (
    card_id     INTEGER PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES accounts(account_id),
    card_type   TEXT,
    last4       TEXT,
    status      TEXT,
    daily_limit REAL
);

CREATE TABLE fee_rules (
    fee_code   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    amount     REAL,
    applies_to TEXT,
    pdf_file   TEXT,
    pdf_page   INTEGER
);

CREATE TABLE transactions (
    txn_id     INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    posted_at  TEXT NOT NULL,
    amount     REAL NOT NULL,
    merchant   TEXT,
    fee_code   TEXT REFERENCES fee_rules(fee_code)
);

CREATE TABLE disputes (
    dispute_id INTEGER PRIMARY KEY,
    txn_id     INTEGER NOT NULL REFERENCES transactions(txn_id),
    opened_at  TEXT,
    reason     TEXT,
    status     TEXT,
    resolution TEXT
);

CREATE TABLE calls (
    call_id        INTEGER PRIMARY KEY,
    customer_id    INTEGER REFERENCES customers(customer_id),
    started_at     TEXT,
    verified       INTEGER DEFAULT 0,
    sentiment      TEXT,
    transcript_ref TEXT
);

CREATE TABLE tickets (
    ticket_id   INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    call_id     INTEGER REFERENCES calls(call_id),
    intent      TEXT,
    status      TEXT,
    summary     TEXT
);
"""

TABLES = ["tickets", "calls", "disputes", "transactions", "fee_rules",
          "cards", "accounts", "customers"]


def create_schema(conn: sqlite3.Connection) -> None:
    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(SCHEMA)
