# AfyaPlus RAG Agent System Architecture

## Purpose

The AfyaPlus RAG Agent System answers documented medical-insurance and
clinical-routing questions through a privacy boundary, a tool-using LangChain
agent, and a Qdrant-persisted LlamaIndex knowledge base. It also performs a
limited medication-volume calculation when a qualified clinician supplies
both required inputs.

The system supports routing and policy explanation. It does not diagnose,
prescribe, choose a dose, or replace qualified clinical or insurance review.

## System Context

| Area | Implementation | Responsibility |
|---|---|---|
| User interfaces | Chainlit `/ui` and FastAPI `/chat` | Browser chat and typed API access |
| Shared chat boundary | `app/chat.py` | Apply privacy controls and invoke one agent graph |
| Privacy boundary | `app/safeguards/` | Mask PII before downstream processing and restore approved output |
| Orchestration | LangChain agent and LangGraph | Select tools and maintain per-thread state |
| Chat model | `ChatOpenAI` over Ollama | Interpret requests and compose responses |
| Knowledge pipeline | LlamaIndex | Load, sentence-chunk, and represent manuals and results |
| Embedding and storage | Qdrant Cloud Inference | Embed, persist, and search knowledge chunks |
| Functional tool | LangChain `@tool` | Calculate clinician-supplied dose/concentration volume safely |

## Request Flow

1. Chainlit generates a non-PII UUID for a browser conversation, or an API
   caller supplies a validated `thread_id`.
2. Both interfaces construct the same Pydantic `ChatRequest` and call
   `run_chat()`.
3. The shared service masks supported PII into a request-local
   `PrivacyContext` and sends only `privacy.masked_message` to the agent.
4. LangGraph loads the checkpoint associated with the validated `thread_id`.
5. Memory middleware trims the model-visible history to recent complete turns.
6. The model either answers within its allowed scope or selects one of the two
   registered tools.
7. Knowledge questions retrieve local source nodes without a second synthesis
   model inside LlamaIndex.
8. The agent produces its final masked response.
9. The privacy context restores only placeholders present in that request's
   vault immediately before the selected interface displays the response.

Detailed call ordering is shown in [sequence-diagram.md](sequence-diagram.md).
Deployment configuration and collection operations are documented in
[deployment.md](deployment.md).

## Grounded Knowledge Pipeline

The knowledge source is the repository's `knowledge/` directory. Ingestion
uses `SimpleDirectoryReader` and LlamaIndex `SentenceSplitter` with 512-token
chunks and 64-token overlap. This avoids local embedding compute; Qdrant Cloud
Inference embeds each chunk during upload.

Vectors live in the `QDRANT_COLLECTION_NAME` collection. The application sends
Qdrant `Document` inference objects using the configured managed model and a
384-dimensional cosine collection. A populated collection is reused without
re-ingesting the manuals. The collection is initialized lazily on the first
knowledge query, and payload metadata is limited to chunk text and source
filename. Source, chunking, model, or dimension changes require a deliberate
new collection or rebuild.

Retrieval uses `similarity_top_k=5`. Qdrant embeds the query and searches the
same collection. The adapter returns LlamaIndex source nodes without asking a
second LLM to synthesize an answer. A
deterministic relevance check retains only nodes that share substantive,
normalized terms with the question. Each retained excerpt receives an inline
filename citation. If none remain, retrieval returns exactly:

```text
Information not found.
```

This validation prevents a nearest vector from being treated as evidence when
the indexed manuals do not actually address the question.

## Agent and Tool Design

`app/agent/agent.py` builds one LangChain agent graph with exactly two tools:

- `search_afyaplus_knowledge` for documented insurance and routing facts.
- `calculate_medication_volume` for `dose_mg / concentration_mg_per_ml` when
  both values were supplied by a qualified clinician.

Both tools have narrow names, typed parameters, explicit docstrings, and
defensive exception handling. Knowledge failures return a temporary
unavailability message. The calculator rejects non-finite, zero, and negative
values and never selects or validates a clinical dose.

The system prompt treats user and retrieved text as untrusted data, requires
citations for policy claims, preserves PII placeholders, prohibits diagnosis
and prescribing, and directs uncertain or high-risk decisions to human review.

## Conversation Memory and Token Management

LangGraph's `InMemorySaver` stores conversation state by `thread_id`. IDs are
restricted to 1-128 letters, digits, underscores, or hyphens so callers cannot
accidentally use free-form PII as a session key. Separate IDs produce isolated
histories.

Chainlit stores a generated `ui-<uuid>` value in `cl.user_session`; it does not
derive the memory key from message text or user PII. A new browser conversation
gets a new key. API clients remain responsible for supplying a safe thread ID.

Before every model call, middleware uses LangChain `trim_messages` with an
approximate token counter and a default history budget of 2,048 tokens. It
keeps recent complete turns, starts on a human message, and ends on a human or
tool message. The full checkpoint remains available in process; only the slice
sent to the model is bounded. The remaining portion of llama3.2's 4,096-token
context is reserved for the system prompt, tool schemas, retrieved evidence,
and output.

`InMemorySaver` is intentionally process-local. Restarting the application
clears conversation memory, and multiple workers do not share it. A durable
checkpointer is required before horizontal production scaling.

## Privacy and Trust Boundaries

The raw message is accepted by Chainlit or FastAPI only long enough to build a
validated request. The shared chat service applies masking before agent,
memory, tool, or model processing. The vault is
request-local and excluded from the privacy context's representation. It is
not stored in LangGraph memory or Qdrant.

De-masking is deliberately last: only the final response is restored, using
only mappings created for the current request. Unknown or invented placeholder
tokens are not expanded. See [privacy.md](privacy.md) for supported patterns,
guarantees, and limitations.

## API and Failure Behavior

The service exposes Chainlit at `/ui`, `GET /health`, and `POST /chat`.
Invalid API schemas return FastAPI's HTTP 422 response. Agent, model, and
tool-loop exceptions are translated to HTTP 503 with a generic message so
internal details are not returned to the caller.

Before `POST /chat` reaches validation or model execution, an in-process
rolling limiter checks a salted hash of the resolved client IP. Railway's
`X-Real-IP` is accepted only when `RATE_LIMIT_TRUST_RAILWAY_PROXY=true`; local
and other deployments ignore that header and use the socket client address.
Exceeded limits return HTTP 429 and `Retry-After` without invoking the agent.

Chainlit converts invalid UI messages and unhandled backend failures into
generic chat messages without returning provider details. Chainlit uses a
WebSocket connection for interactive sessions; this does not change the
shared application privacy boundary.
Its configuration disables file uploads because the current privacy boundary
accepts text messages only. Chain-of-thought/tool-call display defaults to
hidden and is overridable per environment with `CHAINLIT_COT_MODE` (see
[privacy.md](privacy.md)); the LangChain callback handler backing it only
ever observes the already-masked agent invocation, so raw PII is never
exposed even when steps are visible.

The health endpoint is a process liveness check; it does not prove that Ollama
or Qdrant is ready. Production deployment still needs readiness checks,
authentication, structured PII-safe audit events, and monitoring. Endpoint
details are in [api.md](api.md).

## Runtime Configuration

`app/config.py` implements a provider factory: `MODEL_PROVIDER` selects the
chat transport (`ollama_local` default, or `ollama_cloud`) without any code
changes, failing fast at startup on an invalid provider, a missing cloud
model/API key, or a malformed URL. Qdrant retrieval is configured independently
through `QDRANT_*`; switching chat providers never changes the embedding model
or vector store.

At request time, if a chat call to the configured provider fails (e.g. local
Ollama runs out of memory), `build_fallback_middleware()` retries once
against the *other* provider - but only when that other provider is fully
configured (local always has usable defaults; cloud requires
`OLLAMA_CLOUD_MODEL`/`OLLAMA_CLOUD_API_KEY`), and always logs a `WARNING`
naming both providers so a fallback is never silent or ambiguous about which
provider actually answered. If no fallback is available or it also fails,
the original exception propagates to the existing `503` handling below.

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_PROVIDER` | `ollama_local` | Chat transport: `ollama_local` or `ollama_cloud` |
| `OLLAMA_LOCAL_BASE_URL` | `http://localhost:11434/v1` | Local OpenAI-compatible Ollama endpoint |
| `OLLAMA_LOCAL_MODEL` | `llama3.2` | Local chat model |
| `OLLAMA_LOCAL_API_KEY` | `ollama` | Placeholder value the local endpoint ignores |
| `LOCAL_TIMEOUT_SECONDS` | `20.0` | Local chat request timeout |
| `OLLAMA_CLOUD_BASE_URL` | `https://ollama.com/v1` | Direct Ollama Cloud endpoint |
| `OLLAMA_CLOUD_MODEL` | *(required in cloud mode)* | Cloud chat model, e.g. `gpt-oss:20b-cloud` |
| `OLLAMA_CLOUD_API_KEY` | *(required in cloud mode)* | Real Ollama Cloud API key |
| `CLOUD_TIMEOUT_SECONDS` | `30.0` | Cloud chat request timeout |
| `AGENT_HISTORY_TOKEN_BUDGET` | `2048` | Maximum approximate history tokens per model call |
| `QDRANT_URL` | *(required)* | Qdrant Cloud HTTPS endpoint |
| `QDRANT_API_KEY` | *(required)* | Qdrant API key, stored only as a secret |
| `QDRANT_COLLECTION_NAME` | `afyaplus_knowledge_base` | Persistent application collection |
| `QDRANT_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Managed embedding model |
| `QDRANT_EMBEDDING_DIMENSIONS` | `384` | Dense vector dimensions |
| `QDRANT_TIMEOUT_SECONDS` | `30.0` | Cloud request timeout |
| `RATE_LIMIT_ENABLED` | `true` | Enable chat abuse prevention |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `10` | Rolling minute allowance per API IP or UI session |
| `RATE_LIMIT_REQUESTS_PER_DAY` | `100` | Rolling 24-hour allowance per API IP or UI session |
| `RATE_LIMIT_TRUST_RAILWAY_PROXY` | `false` | Trust Railway `X-Real-IP`; enable only on Railway |
| `CHAINLIT_COT_MODE` | `hidden` | Chain-of-thought display: `hidden`, `tool_call`, or `full`; keep `hidden` outside local debugging |

`python scripts/verify_provider.py` reports the active chat and Qdrant
model, collection, and host, and confirms both actually connect, without ever
printing secrets.

`.env` and legacy local `storage/` are excluded from Git (this
also covers `triage/.env`, Triage Engine's separate environment file —
see `triage/docs/triage_engine.md`). `.env.example` contains safe example
values only.

## Verification Strategy

The pytest suite covers PII mask/de-mask round trips, shared-boundary model input,
sentence-aware ingestion, persistence reuse, retrieval citations and not-found
behavior, tool validation, per-thread memory isolation, token trimming, API
validation, and the mounted UI route. Stateful Qdrant boundary doubles keep
unit tests local; a separate synthetic-data smoke test verifies the real
managed inference path.

## Design Trade-offs and Remaining Risks

- Qdrant Cloud removes local embedding compute but makes retrieval dependent on
  network availability, cloud credentials, region, and provider governance.
- Qdrant's free managed inference models are US-hosted; this synthetic-data
  prototype requires a separate region/contract review before real PHI.
- Approximate token counting is fast and model-independent but not identical to
  llama3.2 tokenization.
- Lexical source validation is deterministic and conservative but can reject a
  relevant synonym that shares no normalized keyword with the question.
- A question that mixes verification identifiers (member ID, phone, email)
  with a substantive policy question in one message can occasionally return
  `Information not found.` even though the policy question is answerable -
  observed intermittently (roughly 1 in 5 in manual testing) because
  Qdrant's managed query embedding is not guaranteed bit-identical between
  calls, and a compound query can sit near a similarity boundary between the
  verification-requirements chunk and the actually-relevant policy chunk.
  `similarity_top_k` was raised from 3 to 5 for more headroom (low-risk,
  mechanical, no observed downside). A system-prompt instruction telling the
  agent to strip identifiers from the tool query was also tried, but it was
  reverted after live testing showed it made the model *more* unreliable
  overall - it sometimes generalized "strip identifiers from the query" into
  losing track of the identifiers for its own response too, producing a
  generic greeting or re-asking for information already given, which is a
  worse failure mode than a safe refusal. This remains a known,
  not-fully-eliminated limitation - a conservative failure mode (refuses
  rather than guesses), not a hallucination risk.
- Regex masking covers specified identifiers, not every possible personal or
  clinical identifier - see [privacy.md](privacy.md)'s "Not Currently
  Masked" section for the concrete gap (names, National ID, KRA PIN,
  addresses, free-text quasi-identifiers) and why closing it needs more
  than adding regex patterns.
- The current service has no authentication, authorization, durable memory,
  distributed limiter/checkpointer, or production audit sink. Process restarts
  reset limits, and new Chainlit sessions receive new allowances.
- Human review remains required for uncertainty, clinical risk, coverage
  decisions, and any action affecting patient care or benefits.
- PDF ingestion (`app/rag/ingestion.py::_pdf_documents()`) uses `pypdf`
  directly rather than the `llama-index-readers-file` package, to avoid its
  pandas/beautifulsoup4 transitive dependencies for readers this app
  doesn't use. This only extracts plain text (no tables, images, or
  multi-column layout awareness). **Future optimization**: migrate to
  `llama-index-readers-file`'s `PDFReader` (or a more capable reader) if the
  knowledge base needs richer PDF structure, additional file types
  (`.docx`, `.html`, `.csv`), or better multi-column text ordering than
  `pypdf`'s page-by-page extraction provides.

## Future Scaling Priorities

A full audit of known gaps, organized by area, kept current as new gaps are
found rather than left to accumulate only in chat history or commit
messages.

**Retrieval/RAG**
- Lexical (keyword-overlap) grounding is deterministic and conservative but
  not semantic - can reject a relevant synonym with no shared keyword.
- `similarity_top_k=5` and the `_MAX_GROUNDED_SOURCES=2` cap in
  `app/rag/grounding.py` were both tuned reactively against two specific
  production bugs, not from a systematic evaluation - worth a broader test
  pass with a larger, varied question set before treating these numbers as
  final.
- PDF text extraction (`pypdf`) has real layout artifacts (page markers,
  irregular whitespace) that have measurably degraded at least one real
  answer - see the PDF ingestion note above.
- Qdrant's managed query embedding is not guaranteed bit-identical between
  calls - a source of non-determinism outside this app's control.

**Agent/model**
- System-prompt changes are fragile in ways only visible under live
  testing: a change tried during development measurably made responses
  *less* reliable, and no automated test caught it before manual live
  testing did. There is no automated eval harness (a fixed set of Q&A pairs
  run against a real model after any prompt/retrieval change) that would
  catch this class of regression before it reaches production.
- The free-tier `gpt-oss:20b-cloud` chat model has been observed to degrade
  under bursty usage, returning generic non-answers instead of failing
  loudly - no monitoring/alerting exists for this, and the existing
  local/cloud fallback only triggers on hard failures, not degraded-quality
  200 responses.
- Approximate token counting for history trimming is not exact to the
  actual model tokenizer.

**Memory/state**
- `InMemorySaver` (conversation memory) and the in-process rate limiter are
  both process-local - lost on restart, and would silently fragment across
  replicas if the service scaled beyond one worker. `--workers 1` is a
  direct consequence of this, not an independent choice.

**Access control**
- Partially closed for the observability surface: the SPEC-7.4 dashboard
  (`dashboard/`) requires a shared `DASHBOARD_ACCESS_TOKEN` on every route
  except `/metrics`, which stays open only for the private Prometheus scrape
  network. This is a shared secret, not per-user identity or roles.
- The rest of the system still has no authentication or authorization
  anywhere in the codebase (verified by grep, not assumed) - `/chat` and
  `/ui` remain open to anyone reaching the URL. Rate limiting is the only
  abuse control there, scoped to IP (API) or browser session (UI) - never
  tied to a real user identity.
- No role-based access anywhere - within each surface, every caller that
  clears its one gate (rate limit, or the dashboard token) has identical
  capability.

**Observability**
- Partially closed for the live API: `app/observability.py` now exports
  bounded-label (`method`, `route`, `status_class` - no user content, no
  IDs) request-count, duration, and in-progress metrics at `/metrics`, and
  the Grafana "AfyaPlus Executive Observability" dashboard
  (`dashboard/grafana/`) charts real Chat API request rate, p95 latency, and
  error rate over time from that data, alongside the SPEC-7.1-7.3 evaluation
  quality/drift/cost panels.
- Still open: no per-request retrieval-quality signal is captured in
  production - quality tracking remains simulation/evaluation-only (offline
  `evaluation/`/`drift/` runs), not a live measurement of what real users
  actually received. Logs are still stdout-only (read via `railway logs`),
  with no aggregation, retention policy, search, or alerting - the Grafana
  panels cover metrics, not logs. Every production issue found during
  development (free-tier throttling, retrieval context-overload) was caught
  by manual live testing, not by any automated signal, and that remains true
  today.

**Compliance**
- Masking as implemented is a mechanism, not full Kenya Data Protection Act
  (2019) compliance - see privacy.md's "Not Currently Masked" section.
  Consent flows, data-subject access/deletion rights, breach notification,
  ODPC registration, and data-processing agreements with Qdrant/Ollama Cloud
  as third-party processors are all absent.

**Deployment/CI**
- No GitHub-connected auto-deploy; every deploy is a manual `railway up`.
  No branch-protection/required-CI-check gate on `main`.
- No automated dependency vulnerability scanning configured.

### If Prioritizing Next Steps

1. **Add Kenyan National ID and KRA PIN regex patterns** - highest-value,
   lowest-effort PII win, since both are fixed-format like the three
   patterns already implemented.
2. **An automated eval/regression harness for agent behavior** - so a
   prompt or retrieval regression is caught before reaching production,
   not by manual live testing after the fact.
3. **Basic authentication** - even a simple shared-secret or API-key gate
   would close the largest access-control gap at low implementation cost.
4. **Structured logging to a real sink** - so observability does not depend
   on someone manually running `railway logs` during an incident.
