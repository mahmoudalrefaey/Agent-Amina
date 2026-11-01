# Amina: Banking Voice AI Support Agent (v0)

Amina answers a bank customer's call by voice. She verifies the caller, answers from the customer's own data and the bank's fee policies (citing file and page), creates requests only after a spoken "yes", and hands off to a human when she should.

This repo is **v0: one complete call, end to end.** It implements the worked example from the design deck ([docs/](docs/)):

> **Caller:** "ليه اتخصم مني رسوم يوم 3؟" (Why was I charged a fee on the 3rd?)
> **Amina:** "اتخصم 150 جنيه رسوم Overdraft عشان رصيد حسابك نزل تحت الصفر. مكتوبة في صفحة 4 من جدول رسوم CBC. تحب أطلب لك إعفاء؟"

## Architecture (v0)

```
 Browser (Chrome)                         FastAPI service                         Azure
┌──────────────────┐   text    ┌───────────────────────────────┐  chat + tools  ┌──────────────────┐
│ mic → Web Speech │ ────────► │ CallSession (agent.py)        │ ◄────────────► │ Azure OpenAI     │
│ speech-to-text   │           │   tool-calling loop           │                └──────────────────┘
│                  │ ◄──────── │ Tools (tools.py)              │
│ plays reply      │  reply +  │   verify gate · scoped SQL    │   text → mp3   ┌──────────────────┐
│ "behind the      │  trace    │   propose → yes → confirm     │ ─────────────► │ Azure AI Speech  │
│  scenes" panel   │           │ SQLite (local, synthetic)     │                │ (neural voice)   │
└──────────────────┘           └───────────────────────────────┘                └──────────────────┘
```

| Agent in the deck | Where it lives in v0 |
|---|---|
| Voice | Browser speech-to-text + Azure Speech TTS + the LLM's short spoken replies |
| Triage | The LLM picks which tools to call |
| Data | `get_accounts`, `get_cards`, `get_transactions`, `get_disputes` |
| Knowledge | `get_fee_rule` → fee name, amount, **PDF file + page** |
| Action | `propose_ticket` → caller says yes → `confirm_pending_action` |
| Checker | Rules in code: verify gate, per-customer scoping, yes-check before writes |
| Handoff | `handoff` → summary ticket for staff, call marked transferred |

## Safety rules enforced in code (not only in the prompt)

- **Verify first:** every data tool refuses until `verify_caller` matches National ID + date of birth. The caller is locked out after 3 failed attempts.
- **Per-customer, parameterised SQL:** queries are always scoped to the verified `customer_id`.
- **Actions only after a spoken yes:** a ticket is written only if it was proposed on an earlier turn *and* the caller's latest words are a clear yes. "No" cancels it.
- **Privacy:** long digit runs (IDs, card numbers, dates) are redacted from saved transcripts and the trace.
- **Fallback:** if Azure OpenAI fails or times out, Amina says so and transfers to a human.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # then fill in your Azure keys
python -m backend.seed            # creates amina.db with the synthetic bank
uvicorn backend.main:app --reload
```

Open http://localhost:8000 in **Chrome or Edge**, click **Start call**, then **Talk** (or type).

Tests: `pytest` (offline tool tests; one live call test runs when `.env` is present).

## Demo script

Amina speaks **Egyptian Arabic** (voice `ar-EG-SalmaNeural`, speech recognition `ar-EG`).

| Say | Expect |
|---|---|
| "رقمي القومي 29801010123456 وتاريخ ميلادي أول يناير 1998" | Verified, greets Nour |
| "ليه اتخصم مني رسوم يوم 3؟" | 150 EGP overdraft fee, cites page 4 of the CBC fee schedule, offers a waiver |
| "أيوه" | Creates the waiver request and reads back the ticket number (check `GET /tickets`) |
| "الكارت بتاعي شغال؟" | Debit card ending 4421, active |
| "عايز أكلم حد من خدمة العملاء" | Summary written, call transferred |
| Start a new call and give a wrong birth date | Refuses to read any data |

Other test callers: Omar Khaled `28507150201234` / `1985-07-15` (blocked card, international ATM fee); Mariam Adel `30103220112345` / `2001-03-22` (open dispute).

## Data

All data is synthetic and local (`amina.db`, SQLite). The schema follows the deck (slide 9), with one fix: **`customers.date_of_birth` is added**, because callers verify with National ID + birth date and the original schema had no birth date column. Fee-rule page numbers are sample values pointing at the policy PDFs listed in the deck.

## v0 vs. target

| Area | v0 (this repo) | Target (deck) |
|---|---|---|
| Speech | Browser STT, Azure Speech TTS, push-to-talk | Azure Voice Live: streaming, end-of-speech detection, barge-in |
| Phone | Browser only | Azure Communication Services number + call transfer |
| Policies | Fee rules table with file + page | PDFs → Document Intelligence → AI Search (hybrid) RAG |
| Database | Local SQLite | Azure Database for PostgreSQL, read-only role |
| Agents | One LLM with tools | Triage / Data / Knowledge in parallel / Checker |
| Ops | Transcript files | App Insights trace per call, latency per stage, Key Vault |

## Roadmap

1. Index the policy PDFs in Azure AI Search and replace `get_fee_rule` with real retrieval and citations
2. Move audio to Azure Voice Live over WebSocket (streaming, interruptions, < 1 s p95 first reply)
3. ACS phone number and real transfer to the staff console
4. PostgreSQL + Key Vault + Managed Identity, deploy to Azure Container Apps
5. App Insights tracing, scripted-call regression suite, red-team prompts
