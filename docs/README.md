# Amina documentation

Amina is a voice support agent for a bank in Egypt. She speaks Egyptian Arabic, verifies callers, answers from their own records and from the bank's policy documents (citing file and page), creates requests only after a spoken "yes", and hands over to staff. This is an academic, non-commercial project; all customer data is synthetic.

## Documents

| Document | Purpose | Read if you are… |
|---|---|---|
| [design/system-design.md](design/system-design.md) | The system design: requirements, architecture, flows, data, security, operations, testing | everyone |
| [design/decisions.md](design/decisions.md) | Architecture Decision Records: each choice with its alternatives and consequences | reviewing *why* |
| [design/tts.md](design/tts.md) | The custom Egyptian Arabic TTS: licensing, data, fine-tuning, evaluation, inference service, GPU cost | reviewing the speech model |
| [design/roadmap.md](design/roadmap.md) | 2-week plan: owners, dependencies, milestones, acceptance criteria | planning or tracking |
| [reference/Banking Voice AI Support Agent.pdf](reference/Banking%20Voice%20AI%20Support%20Agent.pdf) | The deck presented to the tutor (the starting point) | context |

## Where each review topic is covered

| # | Topic | Location |
|---|---|---|
| 1 | Project overview, requirements and scope | system-design §1 |
| 2 | Functional and non-functional requirements | system-design §2 |
| 3 | High-level architecture and component responsibilities | system-design §3 |
| 4 | Detailed component architecture | system-design §4 |
| 5 | Architecture decisions and justifications | system-design §5, decisions.md |
| 6 | Request and audio data flows | system-design §6 |
| 7 | STT, LLM and custom TTS integration | system-design §7 |
| 8 | TTS training, evaluation and inference | system-design §8, tts.md |
| 9 | Agent and tool execution workflows | system-design §9 |
| 10 | PostgreSQL design, ER diagram, schema | system-design §10 |
| 11 | RAG architecture and ingestion | system-design §11 |
| 12 | Authentication, authorization, security boundaries | system-design §12 |
| 13 | Errors, retries, fallbacks, failure scenarios | system-design §13 |
| 14 | Real-time communication and concurrency | system-design §14 |
| 15 | Azure infrastructure and deployment | system-design §15 |
| 16 | Logging, tracing, monitoring, cost | system-design §16, tts.md §8 |
| 17 | Testing strategy and acceptance criteria | system-design §17, tts.md §6 |
| 18 | Implementation phases and responsibilities | system-design §18, roadmap.md |
| 19 | Risks, trade-offs, open decisions | system-design §19, tts.md §9 |

## Conventions

- Every claim is labelled **Confirmed** (with a source link), **Decision** (see the ADRs), **Assumption** (with a named check), **Target** (to be measured) or **Open**.
- Diagrams are Mermaid and render on GitHub.
- A change to a decision is made in the same pull request that updates its ADR.

## History

- `v0` demo (one call end to end: browser STT, SQLite, Azure TTS) lives on the `azure-speech/demo` branch. It is temporary and is not part of `main`.
