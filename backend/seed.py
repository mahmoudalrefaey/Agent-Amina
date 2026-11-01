"""Create the local SQLite database and fill it with a small synthetic bank.

All people, IDs and amounts are fake. Fee rule page numbers are sample values
pointing at the policy PDFs listed in the deck (slide 10).

Run:  python -m backend.seed
"""
from datetime import date, timedelta

from backend.db import create_schema, db_path, get_conn


def fee_month_start(today: date) -> date:
    """First day of the latest month whose 3rd has already happened."""
    if today.day >= 3:
        return today.replace(day=1)
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def seed(today: date | None = None) -> None:
    today = today or date.today()
    m = fee_month_start(today)

    def d(day: int, hh: str = "10:00") -> str:
        return f"{m.replace(day=day).isoformat()} {hh}"

    conn = get_conn()
    create_schema(conn)

    conn.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?)",
        [
            (1, "Nour Hassan", "+201001234567", "retail", "2019-04-10", "29801010123456", "1998-01-01"),
            (2, "Omar Khaled", "+201112345678", "premium", "2015-09-01", "28507150201234", "1985-07-15"),
            (3, "Mariam Adel", "+201223456789", "youth", "2022-02-14", "30103220112345", "2001-03-22"),
        ],
    )
    conn.executemany(
        "INSERT INTO accounts VALUES (?,?,?,?,?,?)",
        [
            (101, 1, "current", "EGP", 8420.50, "active"),
            (102, 1, "savings", "EGP", 52000.00, "active"),
            (201, 2, "current", "EGP", 134250.75, "active"),
            (301, 3, "current", "EGP", 2310.00, "active"),
        ],
    )
    conn.executemany(
        "INSERT INTO cards VALUES (?,?,?,?,?,?)",
        [
            (1001, 101, "debit", "4421", "active", 20000),
            (2001, 201, "debit", "7788", "blocked - 3 wrong PIN attempts", 50000),
            (3001, 301, "debit", "1290", "active", 10000),
        ],
    )
    conn.executemany(
        "INSERT INTO fee_rules VALUES (?,?,?,?,?,?)",
        [
            ("OD_FEE", "Overdraft fee", 150, "current account balance goes below zero",
             "cbc_personal_fees_2025.pdf", 4),
            ("ATM_INTL", "International ATM withdrawal fee", 75, "ATM cash withdrawal outside Egypt",
             "1stsource_personal_fee_schedule_2022.pdf", 2),
            ("CARD_REPL", "Card replacement fee", 100, "replacing a lost or damaged card",
             "cbc_personal_fees_2025.pdf", 6),
            ("MONTHLY_MAINT", "Monthly maintenance fee", 25, "current accounts below minimum balance",
             "bankofireland_fees_2020.pdf", 3),
        ],
    )
    conn.executemany(
        "INSERT INTO transactions (account_id, posted_at, amount, merchant, fee_code) VALUES (?,?,?,?,?)",
        [
            # Nour: a purchase on the 2nd takes the balance below zero, overdraft fee on the 3rd.
            (101, d(1, "09:15"), -1250.00, "Carrefour Maadi", None),
            (101, d(2, "18:40"), -6900.00, "B.TECH Electronics", None),
            (101, d(3, "00:05"), -150.00, "Bank fee", "OD_FEE"),
            (101, d(5, "08:00"), 15000.00, "Salary - Acme Egypt", None),
            (101, d(6, "13:20"), -320.00, "Uber", None),
            (101, d(1, "00:10"), -25.00, "Bank fee", "MONTHLY_MAINT"),
            # Omar: international ATM withdrawal and its fee.
            (201, d(2, "11:00"), -4000.00, "ATM Dubai Mall", None),
            (201, d(2, "11:01"), -75.00, "Bank fee", "ATM_INTL"),
            # Mariam: a charge she disputes.
            (301, d(1, "21:30"), -899.00, "StreamPlus Subscription", None),
        ],
    )
    disputed = conn.execute(
        "SELECT txn_id FROM transactions WHERE merchant = 'StreamPlus Subscription'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO disputes (txn_id, opened_at, reason, status, resolution) VALUES (?,?,?,?,?)",
        (disputed, d(2), "Subscription cancelled but still charged", "under review", None),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    seed()
    print(f"Seeded synthetic bank into {db_path()}")
