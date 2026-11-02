# Amina — Architecture Decision Records

Each record has the same sections: **Context**, **Decision**, **Alternatives considered**, **Consequences**. Status is *Proposed* until the design review approves it, and *Accepted* after. The labels (Confirmed / Assumption / Open) mean the same as in [system-design.md](system-design.md).

| ADR | Title | Status |
|---|---|---|
| [001](#adr-001-decoupled-speech-pipeline-instead-of-voice-live) | Decoupled speech pipeline instead of Voice Live | Proposed |
| [002](#adr-002-custom-tts-model-niletts-xtts) | Custom TTS model: NileTTS-XTTS | Proposed |
| [003](#adr-003-tts-hosting-container-apps-serverless-gpu) | TTS hosting: Container Apps serverless GPU | Proposed |
| [004](#adr-004-tts-transport-http-chunked-streaming) | TTS transport: HTTP chunked streaming | Proposed |
| [005](#adr-005-azure-neural-tts-as-fallback-voice) | Azure Neural TTS as fallback voice | Proposed |
| [006](#adr-006-browser-transport-websocket-with-pcm) | Browser transport: WebSocket with PCM | Proposed |
| [007](#adr-007-turn-detection) | Turn detection | Proposed |
| [008](#adr-008-llm-api-azure-openai-responses-api) | LLM API: Azure OpenAI Responses API | Proposed |
| [009](#adr-009-seven-roles-as-modules-one-llm-on-the-hot-path) | Seven roles as modules, one LLM on the hot path | Proposed |
| [010](#adr-010-postgresql-18-sqlalchemy-core-asyncpg-alembic) | PostgreSQL 18, SQLAlchemy Core, asyncpg, Alembic | Proposed |
| [011](#adr-011-authorization-session-scope-plus-row-level-security) | Authorization: session scope plus row-level security | Proposed |
| [012](#adr-012-caller-verification) | Caller verification | Proposed |
| [013](#adr-013-in-process-call-state-no-redis) | In-process call state, no Redis | Proposed |
| [014](#adr-014-rag-on-azure-ai-search-with-push-ingestion) | RAG on Azure AI Search with push ingestion | Proposed |
| [015](#adr-015-hosting-azure-container-apps) | Hosting: Azure Container Apps | Proposed |
| [016](#adr-016-iac-and-delivery-bicep-azd-github-actions) | IaC and delivery: Bicep, azd, GitHub Actions | Proposed |
| [017](#adr-017-identity-and-secrets) | Identity and secrets | Proposed |
| [018](#adr-018-staff-console-and-v1-handoff-model) | Staff console and v1 handoff model | Proposed |
| [019](#adr-019-observability-with-opentelemetry) | Observability with OpenTelemetry | Proposed |
| [020](#adr-020-web-frontend-react-spa-served-by-the-api) | Web frontend: React SPA served by the API | Proposed |
| [021](#adr-021-python-toolchain) | Python toolchain | Proposed |

---

## ADR-001: Decoupled speech pipeline instead of Voice Live

**Context.**

- The deck put Azure Voice Live at the centre: one WebSocket handling STT, the LLM, TTS, VAD, barge-in and noise suppression.
- The tutor judged Azure's Egyptian Arabic voices insufficient. The team will therefore use its own TTS model ([ADR-002](#adr-002-custom-tts-model-niletts-xtts)).
- **Confirmed** facts about Voice Live:
  - Audio output can use only OpenAI voices or Azure TTS voices (standard, custom neural or personal) ([API reference](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-api-reference-2025-10-01), [FAQ](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-faq)).
  - A text-only output mode exists (`modalities: ["text"]`).
  - `ar-EG` is not in the automatic multilingual STT model; it has to be configured explicitly ([language support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/voice-live-language-support)).

**Decision.**

- Run three independent services, orchestrated by `amina-api`:
  - **Azure Speech SDK** streaming STT (`ar-EG`);
  - **Azure OpenAI** Responses API, streaming with tool calls;
  - our **amina-tts** service.
- Azure Neural TTS stays available as the fallback voice.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| **A. Voice Live, end to end** | Cannot speak with our model. This is the hard blocker. |
| **B. Voice Live in text-only mode + our TTS** | Technically possible, and it would give us Voice Live's VAD, noise suppression and tool loop. But its interruption handling (`auto_truncate`) assumes Voice Live played the audio. With our own playback we would have to keep its conversation state consistent ourselves, through an API designed for a different ownership model. Tool calling would also run inside Voice Live's session protocol (preview features change between API versions), so we would debug two state machines instead of one. |
| **C. Realtime speech-to-speech model** (`gpt-realtime`) | Its voices are fixed and not Egyptian, so it fails the tutor's requirement for the same reason as A. |
| **D. Self-hosted STT** (e.g. Whisper) | Adds a second GPU workload. Azure `ar-EG` real-time STT is **Confirmed** available and managed. |
| **E. Voice agent framework** (Pipecat or LiveKit Agents) | These provide exactly the orchestration we need (VAD, interruptions, pipelines). They were rejected for v1 because they bring their own transport assumptions (LiveKit needs an SFU), they put a framework layer between us and the timing we must measure and explain, and our pipeline is small (§7). Reconsider if the turn-taking code grows beyond about 1,000 lines. |

**Consequences.**

- (+) Full control of the voice, of the turn-taking parameters, and of every latency stage, which we can measure separately.
- (+) Each service can be replaced independently. For example, the TTS engine can be swapped behind the same contract.
- (−) We own end-of-turn detection, barge-in, cancellation, and keeping history consistent after interruptions. These are covered in system-design §7.1, §6.4 and §9.3, and tested in the pipeline tests.
- (−) Echo cancellation and noise suppression come from the browser (`getUserMedia` constraints), not from server-side processing. For ACS telephony in phase 2, echo is less of an issue because the handset path is separate.

---

## ADR-002: Custom TTS model: NileTTS-XTTS

**Context.**

- We need natural Egyptian Arabic. The team proposed fine-tuning NileTTS-XTTS with the voice of SPEAKER_02, the female speaker.
- **Confirmed** facts:
  - The NileTTS-XTTS model card reports WER 26.8 → 18.8% and CER 8.1 → 4.1% against base XTTS v2, and speaker similarity 0.713 → 0.755 ([model card](https://huggingface.co/KickItLikeShika/NileTTS-XTTS)).
  - The dataset has 38.1 h, 2 speakers, and is synthetic (NotebookLM). Its sales/customer-service domain covers 21.0 h ([dataset card](https://huggingface.co/datasets/KickItLikeShika/NileTTS-dataset)).
  - The XTTS v2 weights are under the **Coqui Public Model License (non-commercial)**. Coqui has closed, and no commercial licence can be bought ([maintainer statement](https://github.com/idiap/coqui-ai-TTS/discussions/216)).
- The project is academic and non-commercial (user decision).

**Decision.**

- Start from **NileTTS-XTTS, not base XTTS v2**: it already improves Egyptian intelligibility by a large margin on the authors' evaluation.
- Fine-tune on **SPEAKER_02 data only**, plus best-of-N synthetic banking sentences in the same voice.
- Ship the fine-tuned checkpoint **only if it passes the ship gate** ([tts.md §6.4](tts.md#64-ship-gate)). Otherwise ship base NileTTS-XTTS with the text normaliser.
- Treat the weights as CPML, regardless of the "Apache-2.0" label on the model card.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Fine-tune from base XTTS v2 | Throws away the Egyptian adaptation that NileTTS already paid for; needs more data and time to reach the same point. |
| Azure Neural TTS (`ar-EG-SalmaNeural`) | Rejected by the tutor on quality; kept as fallback ([ADR-005](#adr-005-azure-neural-tts-as-fallback-voice)). |
| Azure Custom Neural Voice (professional voice) | Needs a consenting human voice talent and Limited Access approval. Our voice is synthetic, so it doesn't apply and wouldn't be ready in 2 weeks. |
| Chatterbox-based Egyptian models (e.g. [NAMAA-Egyptian-TTS](https://huggingface.co/NAMAA-Space/NAMAA-Egyptian-TTS), MIT) | Commercially licensable, and the right choice if Amina ever goes commercial. Not chosen: the team chose XTTS, the project is non-commercial, and NileTTS has published Egyptian evaluation numbers. The TTS contract is engine-agnostic, so swapping later is a model change, not an architecture change. |
| F5-TTS / Habibi-TTS Egyptian | Mixed licences across dialect checkpoints; no published streaming path we could verify. |
| Mix in human banking recordings | Would create a second speaker identity inside "Amina" (user decision: synthetic SPEAKER_02 only). |

**Consequences.**

- (+) The best published Egyptian starting point, plus a clear and measurable gate.
- (−) Non-commercial only. Commercial use would require replacing the engine.
- (−) Training on the model's own (filtered) outputs mostly reinforces what it already does well. Expected gains come from text normalisation and best-of-N selection for banking vocabulary, not from new acoustic information. That is why the gate exists.
- (−) XTTS is known for occasional artefacts on very short inputs and at the ends of utterances. Mitigations are in [tts.md §7.4](tts.md#74-output-safeguards).

---

## ADR-003: TTS hosting: Container Apps serverless GPU

**Context.**

- `amina-tts` needs a GPU, a streaming HTTP endpoint inside our network, managed identity, and low operations overhead.
- **Confirmed** facts:
  - Container Apps serverless GPUs (T4, A100) are GA, billed per second, and can scale to zero ([GA](https://techcommunity.microsoft.com/blog/appsonazureblog/announcing-ga-for-azure-container-apps-serverless-gpus/4394302)).
  - The T4 profile is 1× T4, 8 vCPU, 56 GiB ([overview](https://learn.microsoft.com/en-us/azure/container-apps/gpu-serverless-overview)).
  - A100 capacity is currently constrained in several regions ([issue #1844](https://github.com/microsoft/azure-container-apps/issues/1844)).
  - Cold starts with large CUDA images and model downloads take minutes, not seconds, according to user reports.

**Decision.**

- Deploy `amina-tts` as a Container App on the `Consumption-GPU-NC8as-T4` profile, in the **same environment** as `amina-api`, with internal ingress.
- Keep at least one replica running during demo and work hours (cron scale rule); allow max 2 replicas.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Azure ML managed online endpoint | Mature model hosting, but it is designed for request/response scoring. Chunked streaming responses and internal-network calls from Container Apps need extra networking (private endpoints). It is also a second platform to learn and operate in 2 weeks. |
| AKS with a GPU node pool | Most control; far too much operations work for a 3-person, 2-week project. |
| GPU VM (NC T4) | Cheap per hour and always warm, but we would handle patching, TLS, deployment, health checks and identity ourselves. It is the fallback plan if the Container Apps GPU quota is denied ([roadmap](roadmap.md)). |
| Third-party GPU hosting | The architecture requires everything to run on Azure. |

**Consequences.**

- (+) Same deployment model, identity and networking as the API; per-second billing; managed TLS and revisions.
- (−) Region choice is constrained by T4 availability. GPU quota must be requested on day 1.
- (−) Cold start measured in minutes, so the always-on window is a cost item ([tts.md §8](tts.md#8-gpu-sizing-scaling-and-cost)).

---

## ADR-004: TTS transport: HTTP chunked streaming

**Context.**

- The API sends one sentence at a time and needs audio as soon as possible, with cheap cancellation on barge-in.

**Decision.**

- `POST /v1/synthesize` with a JSON body.
- The response is `audio/L16; rate=24000` with chunked transfer encoding.
- Cancellation means the client closes the connection.

The contract is in system-design §14.4.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| WebSocket per call | Its advantage, a persistent connection, matters little inside a VNet. It needs sticky routing, in-band cancel messages, and multiplexing per utterance. |
| gRPC server streaming | A good fit technically. Rejected because of the protobuf toolchain and the HTTP/2 ingress configuration, and because `curl`-level debugging is valuable for a 2-week project. |
| Return a whole WAV per sentence | Simplest, but loses streaming. First audio would wait for the full sentence to be synthesised. |

**Consequences.**

- (+) Stateless, load-balanced by ingress, and trivial to test.
- (−) One HTTP request per sentence. The overhead is negligible inside the environment with connection keep-alive (httpx pool).

---

## ADR-005: Azure Neural TTS as fallback voice

**Context.**

- The deck requires a "fallback speech path if the real-time path is down".
- `amina-tts` is a single GPU replica.

**Decision.**

- On a TTS timeout, 429 or 5xx, switch the call **permanently** (for that call) to Azure Neural TTS `ar-EG-SalmaNeural`, with output as raw 24 kHz 16-bit mono PCM.
- Log a `tts_fallback` event and set `calls.voice_used = 'fallback'`.
- The user accepted the voice change.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Hand off instead | A TTS outage would turn every call into a handoff. |
| Retry `amina-tts` per sentence | The voice would flip between engines within one call, and each failed retry adds latency. |

**Consequences.**

- (+) TTS outages and GPU saturation degrade voice quality, not availability.
- (−) The voice changes mid-call. This is visible in the trace and the console.

---

## ADR-006: Browser transport: WebSocket with PCM

**Context.**

- The browser is the only caller channel in v1.
- We need bidirectional, low-latency audio plus control messages.

**Decision.**

- One WebSocket per call.
- **Uplink:** PCM16 at 16 kHz, mono, in 20 ms frames. 16 kHz is what the STT service works with natively.
- **Downlink:** PCM16 at 24 kHz, mono, with a 4-byte utterance sequence header. 24 kHz is XTTS's native output rate.
- JSON text frames for control messages.
- Capture and playback use AudioWorklets, with the browser's echo cancellation, noise suppression and AGC enabled.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| WebRTC (LiveKit or similar) | Better on lossy networks, with built-in jitter buffers and Opus. Needs an SFU or media server plus TURN. That is new infrastructure, and it buys nothing for a demo on decent networks. Also, the ACS media path we add later is WebSocket-based. |
| Opus over WebSocket | Saves bandwidth, but needs encoder and decoder code on both sides. PCM bandwidth (~256 / ~384 kbit/s) is fine. |
| Browser talks directly to Azure Speech | Would split the pipeline across client and server, put token minting for Speech in the browser, and break our server-side barge-in logic. |

**Consequences.**

- (+) Simple, debuggable, one connection.
- (−) No jitter buffer beyond our playback ring buffer, and poorer behaviour on bad networks. Acceptable for v1.

---

## ADR-007: Turn detection

**Context.**

- Without Voice Live we decide ourselves when the caller has finished speaking and when they are interrupting.
- **Confirmed** facts:
  - `Speech_SegmentationSilenceTimeoutMs` accepts values from 100 to 5000 ms; 500 ms is the typical default.
  - Semantic segmentation "shouldn't be used in the single recognition mode or interactive scenarios" and isn't available for all locales ([docs](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech?pivots=programming-language-python)).

**Decision.**

- **End of turn** is the STT `recognized` event (silence segmentation), starting at 500 ms and tuned between 400 and 800 ms.
- **Barge-in** is triggered by STT *partial* results while Amina is speaking: a partial transcript of ≥ 2 words, or ≥ 400 ms of recognised speech. Raw VAD alone does not trigger it.
- **Merge rule:** a new final that arrives before Amina has spoken merges into the current turn.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Semantic segmentation | Documented as not for interactive use; `ar-EG` support is unconfirmed. |
| Client-side VAD (Silero in the browser) for barge-in | Faster to detect sound, but coughs and background noise cause false stops. Transcript-based detection is slower (~300–500 ms) but means the caller actually said words. We measure `false_barge_ins` and can add VAD as a fast pre-signal later. |
| A turn-detection model (end-of-utterance classifier) | Better at telling a thinking pause from a finished sentence. There is no verified Egyptian Arabic model, and it adds another model to host. Phase 2 candidate. |

**Consequences.**

- (+) No extra models; the parameters are few and measurable.
- (−) Every turn pays the silence timeout (~0.5 s). Barge-in detection is slower than with VAD.

---

## ADR-008: LLM API: Azure OpenAI Responses API

**Context.**

- We need streaming text, tool calling (including parallel calls), and no server-side storage of conversations.
- **Confirmed:** the v1 API, including Responses, is GA on Azure OpenAI; `api-version` is no longer required; Microsoft recommends Responses for Azure OpenAI models ([v1 lifecycle](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle)).

**Decision.**

- Use the official `openai` Python SDK against `https://<resource>.openai.azure.com/openai/v1/`, authenticated with an Entra token provider.
- Call the Responses API with `stream=True` and `store=False`.
- We own the conversation history.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Chat Completions | Still supported and familiar from v0. Responses is the recommended path for new work, and the migration cost is the same now as later. |
| Foundry Agent Service | Server-side threads and tools. We need sub-second control of streaming, cancellation mid-stream, and our own tool gates; a hosted agent loop hides exactly those. |
| LangGraph / Microsoft Agent Framework | Useful for multi-agent graphs. We have one LLM loop with about 10 tools ([ADR-009](#adr-009-seven-roles-as-modules-one-llm-on-the-hot-path)), so a framework would add abstraction without removing code. |

**Consequences.**

- (+) A direct, observable streaming loop; easy cancellation.
- (−) **Assumption:** the Responses API is available in our chosen region. Checked on day 1; Chat Completions is the drop-in alternative, behind a thin `llm.py` interface.

---

## ADR-009: Seven roles as modules, one LLM on the hot path

**Context.**

- The deck lists seven agents: Voice, Triage, Data, Knowledge, Action, Checker and Handoff.
- If each were an LLM call, a tool turn would chain triage → planner → data agent → knowledge agent → checker → voice. That is about 4–6 sequential model calls at several hundred ms each, against a ~1 s budget.

**Decision.**

- Keep the seven **roles** as named modules with clear boundaries and their own trace spans.
- Only the Voice LLM runs on the hot path. Triage and summary use a small model asynchronously. The Checker is deterministic, plus a post-call review.

The mapping is in system-design §3.3.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Seven LLM agents (orchestrator + specialists) | Latency, cost, and more ways to fail. It also makes behaviour harder to test deterministically. |
| One undifferentiated LLM loop (v0) | Fast, but the safety rules lived partly in prompts. Roles make ownership and testing explicit. |

**Consequences.**

- (+) The architecture matches the deck's vocabulary for the review while keeping latency low.
- (+) The safety-critical behaviour (verification, scoping, yes-check, grounding) is code, so it is testable.
- (−) Routing quality depends on one model's tool selection. The known-answer eval measures it.

---

## ADR-010: PostgreSQL 18, SQLAlchemy Core, asyncpg, Alembic

**Context.**

- PostgreSQL is mandatory (user decision), and SQLite must be fully removed.
- **Confirmed:** PG 18 is GA on Flexible Server in all public regions, with Entra ID, in-place major upgrades and 80+ extensions ([announcement](https://techcommunity.microsoft.com/blog/adforpostgresql/postgresql-18-now-ga-on-azure-postgres-flexible-server/4469802)).

**Decision.**

- **PostgreSQL 18.**
- Data access through **SQLAlchemy 2 Core** (table metadata + SQL expressions, no ORM), on **asyncpg**.
- Migrations with **Alembic**, written SQL-first.
- `postgres:18` for local development and CI.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| PostgreSQL 17 | Supported, but PG 18 is GA, offers native `uuidv7()` and async I/O improvements, and starting a new system on the older major means an upgrade sooner. No dependency of ours needs 17. |
| SQLAlchemy ORM | Our queries are a dozen read shapes plus a few inserts. Core keeps SQL visible, which helps with RLS and per-transaction `SET LOCAL`, and avoids session and identity-map semantics in an async real-time path. |
| psycopg 3 (async) | Equally good. asyncpg has the more mature SQLAlchemy async integration and is faster on simple queries. Either is defensible; we pick one. |
| Raw SQL files + a hand-written runner | No autogeneration, no downgrade discipline, reinvented tooling. |

**Consequences.**

- (+) Explicit SQL, a typed metadata model, standard migrations.
- (−) Entra token auth needs a connect hook that injects a fresh token as the password (system-design §10.5).

---

## ADR-011: Authorization: session scope plus row-level security

**Context.**

- The most damaging failure would be one caller hearing another customer's data.

**Decision.**

Five layers:

1. state-gated tools;
2. the customer id comes only from the verified session, never from LLM arguments;
3. explicit `customer_id` predicates in SQL;
4. Postgres **RLS** keyed on a transaction-local setting (`SET LOCAL amina.customer_id`);
5. a DB role without UPDATE or DELETE on bank data.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| App-level filtering only (v0) | One forgotten predicate leaks data. |
| A separate DB connection or role per customer | Not workable with pooling and managed identity. |

**Consequences.**

- (+) A missing predicate fails closed (no rows).
- (−) Every scoped query must run in a transaction with `SET LOCAL`. This is enforced by the `customer_scope()` helper and by integration tests.
- (−) RLS doesn't protect against a compromised API process. It is defence in depth against bugs, and is documented as such.

---

## ADR-012: Caller verification

**Context.**

- The deck specifies National ID + date of birth, spoken.
- Speech recognition of 14 spoken Arabic digits is error-prone.
- The pair is knowledge-based authentication, which is weak.

**Decision.**

- Verify with National ID + DOB.
- The ID is stored only as `HMAC-SHA256(pepper)`.
- An on-screen **keypad** is the preferred way to enter the ID; the digits bypass both STT and the LLM.
- Responses are uniform, so they never reveal which factor was wrong.
- Lockouts: per call (3), per ID (5 per 24 h), and per IP (10 failed calls per hour).

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| OTP to the registered phone (ACS SMS) | Much stronger, and recommended for production. Needs an ACS SMS number and sender registration, which is out of v1 scope. Designed here as the phase-2 second factor. |
| Voice biometrics | Out of scope; contentious accuracy and spoofing issues. |
| Plaintext ID lookup (v0) | A database leak would expose national IDs. |

**Consequences.**

- (+) Practical for a demo, and the ID never reaches the LLM when the keypad is used.
- (−) Still knowledge-based. The review must understand that this is acceptable only with synthetic data.

---

## ADR-013: In-process call state, no Redis

**Context.**

- The deck listed Redis as optional for call state.
- A call's media path is a WebSocket pinned to one replica.
- The console needs events from calls running on any replica.

**Decision.**

- Keep all live call state in the `CallSession` object in the process that holds the WebSocket.
- Persist durable facts (events, tickets, summaries) to Postgres as they happen.
- For console fan-out, use Postgres `LISTEN/NOTIFY`. Notification payloads are tiny (`call_id`, event kind; the NOTIFY payload limit is 8000 bytes), and consoles fetch details over REST.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Redis for session state | Externalised state only helps if another replica can resume the call. In a browser WebSocket design, the media connection dies with the replica, so there is nothing to resume. It would add a service, a network hop per state change, and serialisation of complex objects. |
| Redis / Azure Web PubSub / Service Bus for console fan-out | Valid, but it adds infrastructure for a low-volume event stream that Postgres handles natively. |

**Consequences.**

- (+) No extra infrastructure, and no state-consistency bugs between memory and cache.
- (−) A replica crash drops its active calls. This is accepted and documented in system-design §13.
- (−) Each API replica holds one dedicated `LISTEN` connection.

---

## ADR-014: RAG on Azure AI Search with push ingestion

**Context.**

- We need Arabic + English policy retrieval with exact page citations over fewer than 10 PDFs, some of which may be scanned.

**Decision.**

- Ingest with our own CLI: Document Intelligence `prebuilt-layout` (markdown + pages), a page-bounded chunker that keeps tables whole, Azure OpenAI embeddings, and pushes to an **Azure AI Search** index.
- Retrieval is hybrid (BM25 with the `ar.microsoft` or `ar.lucene` analyzer, plus vectors) with the semantic ranker.
- Fee rules link to `(doc_id, page)` deterministically.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Indexer + skillset (integrated vectorization, Document Layout skill) | No ingestion code to write, but page-number propagation through skillset projections is harder to verify and debug, and iteration is slower. With fewer than 10 documents, push is simpler and fully testable. |
| pgvector in our PostgreSQL 18 | One less service. But we would have to implement hybrid fusion ourselves, and there is no managed semantic re-ranker and no Microsoft Arabic analyzer. AI Search is also in the approved deck. Reconsider if cost matters more than retrieval quality. |
| Long-context stuffing (send whole PDFs to the LLM) | Latency and cost per turn are unacceptable for voice; citations would be unreliable. |

**Consequences.**

- (+) Exact pages, testable chunking, and good Arabic lexical matching combined with semantic ranking.
- (−) AI Search Basic is a fixed monthly cost. We maintain about 200 lines of ingestion code.

---

## ADR-015: Hosting: Azure Container Apps

**Context.**

- We need a long-lived WebSocket service that autoscales, plus a GPU service, jobs, managed identity, VNet, and built-in auth.

**Decision.**

- Azure Container Apps, with one environment holding the CPU and GPU workload profiles.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| App Service | WebSockets are fine, but there is no serverless GPU in the same platform, and jobs are weaker. |
| AKS | Too much operations work for the team and timeline. |
| Azure Functions | Not suited to long-lived bidirectional audio sessions. |

**Consequences.**

- (+) One platform for API, TTS, jobs and auth.
- (−) The platform has some limits, for example scale rules for WebSocket concurrency. These are tracked as assumptions.

---

## ADR-016: IaC and delivery: Bicep, azd, GitHub Actions

**Decision.**

- Bicep modules for every resource.
- The Azure Developer CLI (`azd`) for provisioning and deployment, including a pre-deploy hook that runs the migration job.
- GitHub Actions with **OIDC federated credentials**, so no stored cloud secrets.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Terraform | Excellent, but Bicep has day-0 support for new Azure resource types and API versions (GPU profiles, authConfigs), and `azd` gives the team a one-command workflow. |
| Click-ops / scripts | Not repeatable; fails NFR-9. |

**Consequences.**

- (+) `azd up` reproduces the environment.
- (−) Azure-only. That is acceptable, because the target is Azure-only.

---

## ADR-017: Identity and secrets

**Decision.**

- User-assigned managed identities for `amina-api`, `amina-tts` and deploy.
- Entra-only auth on Postgres, AI Services, Search, Storage and Key Vault, with local or key auth disabled.
- Key Vault holds exactly one secret: the national-ID HMAC pepper. The call-token signing key is derived from it with HKDF and a distinct label.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Keys in app settings or Key Vault references (v0 used keys in `.env`) | Keys can leak and must be rotated; managed identity removes them. |

**Consequences.**

- (+) Nothing to rotate except the pepper. Note that rotating the pepper requires re-hashing every national ID, which a migration job handles.
- (−) Local development requires `az login` with data-plane RBAC on the dev resource group.

---

## ADR-018: Staff console and v1 handoff model

**Context.**

- The deck promises a transfer to a human whose console shows the summary, intent, mood, record and live transcript.
- Live voice bridging is the riskiest console feature, and the user marked it optional for v1.

**Decision.**

- The console is a route in the same SPA (`/console`), protected by Container Apps built-in auth (Entra ID, `Amina.Staff` app role). Its live updates come over a WebSocket fed by `LISTEN/NOTIFY`.
- The v1 handoff is **warm handoff to a queue**: the case appears with full context, staff claim it, and the caller hears a reference number plus a callback promise.
- Live voice takeover is designed (system-design §14.7) and scheduled for phase 2.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| A separate console app | A second deployment and auth setup for one screen. |
| Live voice takeover in v1 | Same-replica affinity and an audio bridge; high risk for the timeline. |
| App-implemented MSAL auth | More code than Easy Auth for the same result. |

**Consequences.**

- (+) Shows the full context handover the deck promises.
- (−) In v1 the "transfer" is a callback, not a live transfer. This must be stated plainly in the review.

---

## ADR-019: Observability with OpenTelemetry

**Decision.**

- Use the `azure-monitor-opentelemetry` distro in both services, with one trace per call.
- Custom metrics for every latency stage, plus a redaction span processor.
- Dashboards are an Azure Workbook.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| App Insights classic SDK | Legacy path; OpenTelemetry is the current Microsoft recommendation and is vendor-neutral. |
| Prometheus/Grafana | More infrastructure; App Insights is already in the stack. |

**Consequences.**

- (+) Per-stage latency and the cost per call are visible from the first deployment.

---

## ADR-020: Web frontend: React SPA served by the API

**Decision.**

- React 19 + Vite + TypeScript, built into static files that `amina-api` serves.
- Two routes: `/call` and `/console`.
- Audio is handled in AudioWorklets.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Azure Static Web Apps | A second origin means CORS and a split Easy Auth configuration. Serving from the API keeps one origin, so cookies work for WebSocket auth. |
| Next.js | Server rendering adds nothing here, and it would be another server runtime. |
| Plain HTML (v0) | AudioWorklet code, the console state, and the playback protocol justify a typed build. |

---

## ADR-021: Python toolchain

**Decision.**

- **Python 3.12** for both services and for training.
- A **uv** workspace (`apps/api`, `apps/tts`, `packages/arabic_text`, `training/tts`).
- **ruff** for linting and formatting, **pyright** for types, **pytest** + pytest-asyncio for tests.

**Alternatives considered.**

| Option | Why not chosen |
|---|---|
| Python 3.13/3.14 | The API alone could use 3.13. The TTS stack (PyTorch, coqui-tts, optional DeepSpeed) has the strongest compatibility on 3.12, and one interpreter version across the workspace avoids split tooling. Revisit after v1. **Assumption:** the pinned coqui-tts release supports 3.12; checked on day 1. |
| Poetry / pip-tools | uv is faster, handles workspaces natively, and is the current de-facto standard. |
