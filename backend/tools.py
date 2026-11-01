"""The tools Amina can call, plus their OpenAI function schemas.

Safety rules are enforced here in code, not only in the prompt:
  * No customer data is read until verify_caller succeeds.
  * Every query is scoped to the verified customer_id (parameterised SQL).
  * A ticket is written only via propose_ticket -> caller says yes on a later
    turn -> confirm_pending_action.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from backend.db import get_conn

MAX_VERIFY_ATTEMPTS = 3

YES_RE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|ok|okay|please do|go ahead|do it|confirm|correct|absolutely|of course"
    r"|أيوه|ايوه|أيوة|ايوة|أيو|ايو|نعم|آه|اه|أه|تمام|ماشي|أكيد|اكيد|موافق|موافقة|حاضر|يلا|اعمل|اعمليه|اعمله)\b",
    re.IGNORECASE,
)
NO_RE = re.compile(
    r"\b(no|nope|don't|do not|cancel|stop|never mind|لا|لأ|لاء|بلاش|الغي|الغيه|مش عايز|مش عاوز|مش موافق)\b",
    re.IGNORECASE,
)
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def to_ascii_digits(text: str) -> str:
    return text.translate(ARABIC_DIGITS)


@dataclass
class CallState:
    call_id: int
    customer_id: int | None = None
    verified: bool = False
    verify_attempts: int = 0
    turn: int = 0
    last_user_text: str = ""
    last_agent_text: str = ""
    pending_action: dict | None = None
    transferred: bool = False
    sentiment: str | None = None
    trace: list = field(default_factory=list)


def is_yes(text: str) -> bool:
    return bool(YES_RE.search(text)) and not NO_RE.search(text)


# ---------- helpers ----------

DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y",
]


def parse_date(text: str) -> str | None:
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", to_ascii_digits(text).strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\bof\b|,", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _rows(sql: str, params: tuple) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _require_verified(state: CallState) -> dict | None:
    if not state.verified:
        return {"error": "caller not verified. Ask for National ID and date of birth first."}
    return None


# ---------- tools ----------

def verify_caller(state: CallState, national_id: str, date_of_birth: str) -> dict:
    if state.verified:
        return {"verified": True, "note": "already verified"}
    if state.verify_attempts >= MAX_VERIFY_ATTEMPTS:
        return {"verified": False, "error": "too many failed attempts. Transfer the caller to a human."}
    state.verify_attempts += 1

    nid = re.sub(r"[^0-9]", "", to_ascii_digits(national_id or ""))
    dob = parse_date(date_of_birth or "")
    rows = _rows(
        "SELECT customer_id, full_name FROM customers WHERE national_id = ? AND date_of_birth = ?",
        (nid, dob),
    ) if nid and dob else []
    if not rows:
        left = MAX_VERIFY_ATTEMPTS - state.verify_attempts
        return {"verified": False, "attempts_left": left,
                "error": "details do not match our records" if dob else "could not understand the date of birth"}

    state.verified = True
    state.customer_id = rows[0]["customer_id"]
    with get_conn() as conn:
        conn.execute("UPDATE calls SET customer_id = ?, verified = 1 WHERE call_id = ?",
                     (state.customer_id, state.call_id))
    first_name = rows[0]["full_name"].split()[0]
    return {"verified": True, "first_name": first_name}


def get_accounts(state: CallState) -> dict:
    if err := _require_verified(state):
        return err
    return {"accounts": _rows(
        "SELECT account_id, type, currency, balance, status FROM accounts WHERE customer_id = ?",
        (state.customer_id,),
    )}


def get_cards(state: CallState) -> dict:
    if err := _require_verified(state):
        return err
    return {"cards": _rows(
        """SELECT c.card_type, c.last4, c.status, c.daily_limit, a.currency
           FROM cards c JOIN accounts a ON a.account_id = c.account_id
           WHERE a.customer_id = ?""",
        (state.customer_id,),
    )}


def get_transactions(state: CallState, day_of_month: int | None = None,
                     fees_only: bool = False, limit: int = 15) -> dict:
    if err := _require_verified(state):
        return err
    sql = """SELECT t.txn_id, t.posted_at, t.amount, a.currency, t.merchant, t.fee_code
             FROM transactions t JOIN accounts a ON a.account_id = t.account_id
             WHERE a.customer_id = ? AND t.posted_at >= date(?, '-62 days')"""
    params: list = [state.customer_id, date.today().isoformat()]
    if day_of_month:
        sql += " AND CAST(strftime('%d', t.posted_at) AS INTEGER) = ?"
        params.append(int(day_of_month))
    if fees_only:
        sql += " AND t.fee_code IS NOT NULL"
    sql += " ORDER BY t.posted_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 50)))
    return {"transactions": _rows(sql, tuple(params))}


def get_fee_rule(state: CallState, fee_code: str) -> dict:
    # Policy text is public, but keep the same gate so the flow stays consistent.
    if err := _require_verified(state):
        return err
    rows = _rows("SELECT * FROM fee_rules WHERE fee_code = ?", (fee_code.strip().upper(),))
    return {"fee_rule": rows[0]} if rows else {"error": f"no fee rule found for {fee_code}"}


def get_disputes(state: CallState) -> dict:
    if err := _require_verified(state):
        return err
    return {"disputes": _rows(
        """SELECT d.dispute_id, d.opened_at, d.reason, d.status, d.resolution,
                  t.merchant, t.amount, t.posted_at
           FROM disputes d JOIN transactions t ON t.txn_id = d.txn_id
           JOIN accounts a ON a.account_id = t.account_id
           WHERE a.customer_id = ?""",
        (state.customer_id,),
    )}


def propose_ticket(state: CallState, intent: str, summary: str) -> dict:
    if err := _require_verified(state):
        return err
    state.pending_action = {"intent": intent, "summary": summary, "proposed_turn": state.turn}
    if is_yes(state.last_user_text) and state.last_agent_text.rstrip().endswith(("?", "؟")):
        # The caller already said yes to Amina's offer: create it now instead of asking twice.
        result = confirm_pending_action(state)
        if "ticket_id" in result:
            result["instruction"] = ("Already CREATED because the caller said yes. "
                                     "Tell them the ticket number now. Do not ask for confirmation again.")
        return result
    return {"status": "pending_confirmation",
            "instruction": "Ask the caller a yes/no question to confirm. Do not say it is done."}


def confirm_pending_action(state: CallState) -> dict:
    if err := _require_verified(state):
        return err
    action = state.pending_action
    if not action:
        return {"error": "nothing is pending. Propose a ticket first."}
    # Same-turn is allowed only when the caller's words are a yes to a question Amina just asked.
    answered_offer = state.last_agent_text.rstrip().endswith(("?", "؟"))
    if state.turn <= action["proposed_turn"] and not answered_offer:
        return {"error": "the caller has not answered yet. Wait for their yes."}
    if not is_yes(state.last_user_text):
        state.pending_action = None
        return {"error": "the caller did not clearly say yes. Nothing was created."}

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (customer_id, call_id, intent, status, summary) VALUES (?,?,?,?,?)",
            (state.customer_id, state.call_id, action["intent"], "open - awaiting staff review", action["summary"]),
        )
        ticket_id = cur.lastrowid
    state.pending_action = None
    return {"ticket_id": ticket_id, "status": "open - a staff member will review it"}


def handoff(state: CallState, reason: str, summary: str, mood: str = "neutral") -> dict:
    state.transferred = True
    state.sentiment = mood
    with get_conn() as conn:
        conn.execute("UPDATE calls SET sentiment = ? WHERE call_id = ?", (mood, state.call_id))
        if state.customer_id:
            conn.execute(
                "INSERT INTO tickets (customer_id, call_id, intent, status, summary) VALUES (?,?,?,?,?)",
                (state.customer_id, state.call_id, "handoff", "transferred to staff",
                 f"Reason: {reason}. Summary: {summary}"),
            )
    return {"transferred": True}


TOOLS = {
    "verify_caller": verify_caller,
    "get_accounts": get_accounts,
    "get_cards": get_cards,
    "get_transactions": get_transactions,
    "get_fee_rule": get_fee_rule,
    "get_disputes": get_disputes,
    "propose_ticket": propose_ticket,
    "confirm_pending_action": confirm_pending_action,
    "handoff": handoff,
}


def _fn(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }}


TOOL_SCHEMAS = [
    _fn("verify_caller", "Verify the caller. Required before any account data can be read.",
        {"national_id": {"type": "string", "description": "14-digit Egyptian National ID, Western digits only"},
         "date_of_birth": {"type": "string", "description": "Date of birth as YYYY-MM-DD"}},
        ["national_id", "date_of_birth"]),
    _fn("get_accounts", "List the verified caller's accounts and balances."),
    _fn("get_cards", "List the verified caller's cards with status and daily limit."),
    _fn("get_transactions", "Recent transactions (last ~2 months) for the verified caller.",
        {"day_of_month": {"type": "integer", "description": "Only transactions posted on this day of the month, e.g. 3 for 'the 3rd'"},
         "fees_only": {"type": "boolean", "description": "Only bank fee transactions"},
         "limit": {"type": "integer"}}),
    _fn("get_fee_rule", "Look up the bank's policy for a fee code: name, amount, when it applies, and the policy PDF file and page.",
        {"fee_code": {"type": "string"}}, ["fee_code"]),
    _fn("get_disputes", "List the verified caller's disputes and their status."),
    _fn("propose_ticket", "Prepare a request (e.g. fee waiver, card unblock, dispute) for staff. It is NOT created until the caller says yes.",
        {"intent": {"type": "string", "description": "short label, e.g. fee_waiver, card_unblock, dispute"},
         "summary": {"type": "string", "description": "one or two sentences for the staff member"}},
        ["intent", "summary"]),
    _fn("confirm_pending_action", "Create the proposed request. Call only after the caller has said yes to it."),
    _fn("handoff", "Transfer the call to a human staff member with a summary.",
        {"reason": {"type": "string"}, "summary": {"type": "string"},
         "mood": {"type": "string", "enum": ["calm", "neutral", "frustrated", "angry", "distressed"]}},
        ["reason", "summary"]),
]
