"""Scripted-call tests. Tool tests run offline; the live LLM test needs .env."""
import os

import pytest
from dotenv import load_dotenv

from backend import tools
from backend.db import get_conn
from backend.seed import seed

load_dotenv()

NOUR_ID, NOUR_DOB = "29801010123456", "1998-01-01"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AMINA_DB", str(tmp_path / "test.db"))
    seed()
    with get_conn() as conn:
        call_id = conn.execute("INSERT INTO calls (started_at) VALUES ('now')").lastrowid
    return call_id


@pytest.fixture
def state(fresh_db):
    return tools.CallState(call_id=fresh_db)


def ticket_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]


def test_data_tools_refuse_before_verification(state):
    for name in ["get_accounts", "get_cards", "get_transactions", "get_disputes"]:
        assert "error" in tools.TOOLS[name](state)
    assert "error" in tools.get_fee_rule(state, "OD_FEE")


def test_wrong_details_fail_and_lock_after_three_attempts(state):
    for _ in range(3):
        assert tools.verify_caller(state, NOUR_ID, "1999-01-01")["verified"] is False
    locked = tools.verify_caller(state, NOUR_ID, NOUR_DOB)
    assert locked["verified"] is False and "too many" in locked["error"]


def test_spoken_formats_verify(state):
    r = tools.verify_caller(state, "2980 1010 1234 56", "1st of January 1998")
    assert r == {"verified": True, "first_name": "Nour"}


def test_fee_on_the_3rd_is_found_with_pdf_source(state):
    tools.verify_caller(state, NOUR_ID, NOUR_DOB)
    txns = tools.get_transactions(state, day_of_month=3, fees_only=True)["transactions"]
    assert len(txns) == 1 and txns[0]["fee_code"] == "OD_FEE" and txns[0]["amount"] == -150
    rule = tools.get_fee_rule(state, "OD_FEE")["fee_rule"]
    assert rule["pdf_file"] == "cbc_personal_fees_2025.pdf" and rule["pdf_page"] == 4


def test_data_is_scoped_to_the_verified_customer(state):
    tools.verify_caller(state, NOUR_ID, NOUR_DOB)
    merchants = {t["merchant"] for t in tools.get_transactions(state, limit=50)["transactions"]}
    assert "ATM Dubai Mall" not in merchants  # Omar's transaction
    assert all(c["last4"] == "4421" for c in tools.get_cards(state)["cards"])


def test_ticket_only_after_yes_on_a_later_turn(state):
    tools.verify_caller(state, NOUR_ID, NOUR_DOB)
    state.turn, state.last_user_text = 1, "why was I charged a fee on the 3rd?"
    tools.propose_ticket(state, "fee_waiver", "Waive overdraft fee on the 3rd")
    assert "error" in tools.confirm_pending_action(state)  # same turn: no yes yet
    assert ticket_count() == 0

    state.turn, state.last_user_text = 2, "Yes please"
    r = tools.confirm_pending_action(state)
    assert r["ticket_id"] and ticket_count() == 1


def test_yes_to_an_offer_creates_ticket_in_same_turn(state):
    tools.verify_caller(state, NOUR_ID, NOUR_DOB)
    state.turn, state.last_agent_text, state.last_user_text = 2, "تحب أطلب لك إعفاء؟", "أيوه"
    assert tools.propose_ticket(state, "fee_waiver", "Waive overdraft fee")["ticket_id"]
    assert ticket_count() == 1


def test_no_cancels_the_pending_ticket(state):
    tools.verify_caller(state, NOUR_ID, NOUR_DOB)
    state.turn = 1
    tools.propose_ticket(state, "fee_waiver", "Waive overdraft fee")
    state.turn, state.last_user_text = 2, "No, don't do that"
    assert "error" in tools.confirm_pending_action(state)
    assert state.pending_action is None and ticket_count() == 0


def test_arabic_yes_no_and_digits(state):
    assert tools.is_yes("أيوه من فضلك") and tools.is_yes("تمام اعمله")
    assert not tools.is_yes("لا شكراً") and not tools.is_yes("مش عايز")
    r = tools.verify_caller(state, "٢٩٨٠١٠١٠١٢٣٤٥٦", "١٩٩٨-٠١-٠١")
    assert r["verified"] is True


@pytest.mark.skipif(not os.getenv("AZURE_OPENAI_API_KEY"), reason="needs Azure OpenAI in .env")
def test_live_scripted_call():
    from backend.agent import CallSession

    s = CallSession()
    s.respond(f"رقمي القومي {NOUR_ID} وتاريخ ميلادي أول يناير 1998")
    assert s.state.verified
    r = s.respond("ليه اتخصم مني رسوم يوم 3؟")
    tools_used = {t["tool"] for t in r["trace"]}
    assert {"get_transactions", "get_fee_rule"} <= tools_used
    assert "150" in r["reply"] and any("؀" <= ch <= "ۿ" for ch in r["reply"])  # answered in Arabic
    r = s.respond("أيوه")  # one yes to Amina's waiver offer is enough
    assert ticket_count() == 1 and "1" in r["reply"]
