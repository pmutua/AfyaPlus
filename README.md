# AfyaPlus Enterprise-Grade RAG-Powered Agent System

AfyaPlus is a privacy-aware medical-insurance verification and
clinical-routing assistant. It combines FastAPI and Chainlit interfaces, a
tool-using LangChain/LangGraph agent, a grounded LlamaIndex knowledge pipeline,
Ollama chat models, Qdrant Cloud Inference, and Kenyan PII masking.

The system explains documented policy and routing guidance. It does not
diagnose, prescribe, select medication doses, or replace qualified clinical or
insurance review.

## What Is Implemented

- A Chainlit browser chat at `/ui` plus FastAPI health and chat endpoints.
- Kenyan phone, email, and AfyaPlus member-ID masking before model calls.
- Request-local de-masking immediately before an approved response is returned.
- Sentence-aware LlamaIndex chunking with managed Qdrant embeddings.
- Persistent Qdrant Cloud vectors that reload instead of re-ingesting on restart.
- Deterministic source validation, inline citations, and an exact
  `Information not found.` fallback.
- A LangChain agent with exactly two tools: grounded knowledge retrieval and a
  validated medication-volume calculator.
- Per-thread LangGraph memory with bounded model-visible history.
- Automated tests for privacy, retrieval, grounding, tools, memory, and API
  behavior.

## Architecture

```mermaid
flowchart TD
    User["Browser /ui or API /chat request"]
    Validate["Pydantic validation"]
    Mask["PII masking + request-local vault"]
    Agent["LangChain/LangGraph agent<br/>bounded thread memory"]
    Knowledge["LlamaIndex + Qdrant Cloud<br/>knowledge tool"]
    Calculator["Validated medication-volume tool"]
    Response["Grounded masked response"]
    Demask["Request-local de-masking"]
    Output["Chainlit message or FastAPI response"]

    User --> Validate --> Mask --> Agent
    Agent --> Knowledge --> Response
    Agent --> Calculator --> Response
    Response --> Demask --> Output
```

Detailed documentation:

- [Architecture](docs/architecture.md)
- [Deployment guide](docs/deployment.md)
- [Railway deployment guide (all four SPEC-7.4 services)](docs/railway-deployment.md)
- [Deployment decision record](docs/deployment-architecture-research.md)
- [Sequence diagrams](docs/sequence-diagram.md)
- [Privacy safeguards](docs/privacy.md)
- [API reference](docs/api.md)

## Repository Layout

```text
app/
  agent/                 # Agent, prompt, tools, memory, token trimming
  chainlit_app.py        # Browser chat lifecycle and UI sessions
  chat.py                # Shared privacy-safe chat execution
  models/                # Pydantic request and response schemas
  rag/                   # Chunking, embeddings, ingestion, retrieval, grounding
  safeguards/            # PII patterns, masking, de-masking, API dependency
  config.py              # Ollama local/cloud chat-model provider factory
  main.py                # FastAPI application and mounted Chainlit UI
docs/                    # Primary product documentation
knowledge/               # Local insurance and clinical-routing manuals
tests/                   # Automated test suite
triage/                  # Foundational Week 1 triage engine
  env.example            # Triage's own configuration template
triage_cli.py             # Foundational triage CLI entrypoint
evaluation/               # SPEC-7.1 clinical model comparison pipeline
drift/                    # SPEC-7.2 statistical drift monitoring
cost/                     # SPEC-7.3 token cost/efficiency analysis
dashboard/                # SPEC-7.4 authenticated executive dashboard + Grafana
scripts/                  # Provider verification and executive-brief rendering
executive_summary.md      # SPEC-7.5 evidence-backed leadership brief (source)
executive_summary.pdf     # SPEC-7.5 rendered one-page leadership brief
docker-compose.yml        # Chat API + dashboard + Prometheus + Grafana stack
.env.example             # RAG Agent System configuration template
requirements.txt         # Python dependencies
.chainlit/config.toml    # Safe UI branding and feature settings
```

See "Executive Observability Dashboard (SPEC-7)" below for what the
`evaluation/`, `drift/`, `cost/`, and `dashboard/` packages do and how to run
each phase.

The Qdrant collection is created and populated lazily on the first knowledge
query. Once non-empty, it is reused across restarts. Rebuild into a new
collection after changing knowledge sources, chunking, embedding model, or
dimensions; see the [deployment guide](docs/deployment.md#collection-lifecycle).

Triage Engine and the RAG Agent System each read their own environment file
(`triage/.env` and the repo-root `.env`, respectively) — see "Environment
Configuration" below and [triage/docs/triage_engine.md](triage/docs/triage_engine.md).

## Prerequisites

- Python 3.12 (matches `.python-version`); Python 3.11+ works if you use the
  plain `pip`/`venv` fallback below instead of `uv`.
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip` with Python
  virtual-environment support.
- A Qdrant Cloud cluster with Inference enabled.
- Ollama installed only when using the optional local chat provider.
- Enough local memory to run `llama3.2` when using local chat.

### Installing uv

`uv` manages the Python interpreter and dependency installs together, so it
does not depend on the interpreter's own bundled `pip`/`ensurepip`. Install
it once per machine:

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# Linux and macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/)
for other methods (pipx, Homebrew, etc.).

Install Ollama from its official platform page:

| Platform | Official installer |
|---|---|
| Windows | [Ollama for Windows](https://ollama.com/download/windows) |
| Linux | [Ollama for Linux](https://ollama.com/download/linux) |
| macOS | [Ollama for macOS](https://ollama.com/download/mac) |

After installation, open a new terminal and verify Ollama:

```text
ollama --version
ollama list
```

Desktop installers normally run Ollama in the background. If it is not
running, start it in a separate terminal with `ollama serve`. If that command
reports that port `11434` is already in use, an Ollama service is already
running; do not start a second instance.

## Quick Start

Run all commands from the repository root—the directory containing
`requirements.txt` and `app/`.

### Windows PowerShell

Create the environment and install dependencies with `uv` (recommended — it
manages its own Python 3.12 and does not depend on the interpreter's bundled
`pip`/`ensurepip`, which can be unreliable on some Windows Python installs):

```powershell
uv venv --python 3.12 .venv
$env:UV_HTTP_TIMEOUT = "120"  # some dependencies are large downloads; raise uv's default 30s timeout
uv pip install --python .venv -r requirements.txt
Copy-Item .env.example .env
```

<details>
<summary>Alternative: plain <code>pip</code>/<code>venv</code></summary>

```powershell
py -3 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

</details>

Set `QDRANT_URL` and `QDRANT_API_KEY` in the gitignored `.env` before starting
the application. Keep the application collection dedicated and separate from
unrelated workloads or external tools.

Pull the local models and start the application:

```powershell
ollama pull llama3.2
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Linux

Create the environment and install dependencies with `uv` (recommended):

```bash
uv venv --python 3.12 .venv
UV_HTTP_TIMEOUT=120 uv pip install --python .venv -r requirements.txt  # some dependencies are large downloads; raise uv's default 30s timeout
cp .env.example .env
```

<details>
<summary>Alternative: plain <code>pip</code>/<code>venv</code></summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

If `python3 -m venv` is unavailable, install the virtual-environment package
provided by your Linux distribution, then repeat the command.

</details>

Set `QDRANT_URL` and `QDRANT_API_KEY` in the gitignored `.env` before starting
the application.

Pull the local models and start the application:

```bash
ollama pull llama3.2
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### macOS

Create the environment and install dependencies with `uv` (recommended):

```bash
uv venv --python 3.12 .venv
UV_HTTP_TIMEOUT=120 uv pip install --python .venv -r requirements.txt  # some dependencies are large downloads; raise uv's default 30s timeout
cp .env.example .env
```

<details>
<summary>Alternative: plain <code>pip</code>/<code>venv</code></summary>

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

</details>

Set `QDRANT_URL` and `QDRANT_API_KEY` in the gitignored `.env` before starting
the application.

Pull the local models and start the application:

```bash
ollama pull llama3.2
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Environment Configuration

The RAG API works with the safe local defaults in `.env.example`. Set
`MODEL_PROVIDER` to switch the chat transport between local Ollama and
Ollama Cloud without any code changes; an invalid provider, a missing cloud
model/API key, or a malformed URL fails fast at startup (`app/config.py`).

At request time, if the configured provider fails (e.g. local Ollama runs
out of memory), the agent retries once against the other provider - but
only when it's fully configured, and always with a logged `WARNING` naming
both providers, so a fallback is never silent or ambiguous about which
provider actually answered.

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_PROVIDER` | `ollama_local` | Chat transport: `ollama_local` or `ollama_cloud` |
| `OLLAMA_LOCAL_BASE_URL` | `http://localhost:11434/v1` | Local OpenAI-compatible Ollama endpoint |
| `OLLAMA_LOCAL_MODEL` | `llama3.2` | Local chat model |
| `OLLAMA_LOCAL_API_KEY` | `ollama` | Placeholder value the local endpoint ignores |
| `LOCAL_TIMEOUT_SECONDS` | `20.0` | Local chat-model request timeout |
| `OLLAMA_CLOUD_BASE_URL` | `https://ollama.com/v1` | Direct Ollama Cloud endpoint |
| `OLLAMA_CLOUD_MODEL` | *(required in cloud mode)* | Cloud chat model, e.g. `gpt-oss:120b` |
| `OLLAMA_CLOUD_API_KEY` | *(required in cloud mode)* | Real Ollama Cloud API key — never `ollama` |
| `CLOUD_TIMEOUT_SECONDS` | `30.0` | Cloud chat-model request timeout |
| `AGENT_HISTORY_TOKEN_BUDGET` | `2048` | Approximate history tokens sent per model call |
| `QDRANT_URL` | *(required)* | Qdrant Cloud HTTPS cluster endpoint |
| `QDRANT_API_KEY` | *(required)* | Qdrant Cloud API key; never commit it |
| `QDRANT_COLLECTION_NAME` | `afyaplus_knowledge_base` | Application knowledge collection |
| `QDRANT_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Managed dense embedding model |
| `QDRANT_EMBEDDING_DIMENSIONS` | `384` | Collection vector size for the selected model |
| `QDRANT_TIMEOUT_SECONDS` | `30.0` | Qdrant request timeout |

`CI` is an ambient automation flag, not a local `.env` setting. When present,
it selects a deterministic test embedding instead of contacting Ollama.

Run `python scripts/verify_provider.py` after changing any of the above to
confirm the configured chat and Qdrant providers actually connect — it
never prints secrets.

The foundational triage engine reads its own `triage/.env`
(from `triage/env.example`), not this file — see
[triage/docs/triage_engine.md](triage/docs/triage_engine.md). Never commit
either real `.env`; Git excludes `.env`/`.env.*` at every directory depth,
plus persisted `storage/` data.

## Chat in the Browser or API

When Uvicorn reports that it is running on `http://127.0.0.1:8000`, open:

- Chainlit chat: `http://127.0.0.1:8000/ui/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI schema: `http://127.0.0.1:8000/openapi.json`
- Health endpoint: `http://127.0.0.1:8000/health`

### Windows PowerShell Request

```powershell
$body = @{
    message = "What documents are required for member verification?"
    thread_id = "demo-session-001"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/chat" `
    -ContentType "application/json" `
    -Body $body
```

### Linux and macOS Request

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "What documents are required for member verification?",
    "thread_id": "demo-session-001"
  }'
```

Expected response shape:

```json
{
  "response": "A grounded answer with inline source citations.",
  "thread_id": "demo-session-001"
}
```

Reuse a valid non-PII `thread_id` for related turns. A process restart clears
the current in-memory conversation history.

## Run Tests

Install dependencies first, then run the suite from the repository root.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Linux and macOS:

```bash
.venv/bin/python -m pytest -q
```

Tests use deterministic embeddings where `CI` is set and fake chat models for
model-boundary assertions. They do not require real patient information.

## CI/CD and Railway Production

GitHub Actions runs dependency, test, compilation, and whitespace checks for
pull requests and pushes to `main` or `feat-rag-agent-system`. Production has
no GitHub source connected — every deploy is a manual `railway up`, so CI
passing is not currently a deploy gate. Runtime settings for the chat API are versioned in
`app/railway.json`; the `dashboard`, `prometheus`, and `grafana` services
each have their own config-as-code file under `dashboard/railway/`.
Secrets remain in Railway variables.

See the [deployment guide](docs/deployment.md#railway-production-deployment)
for this service's required variables, initial deployment, verification, and
rollback procedure. Production must use `MODEL_PROVIDER=ollama_cloud`; it
cannot reach a developer workstation's local Ollama service. For the other
three Railway services (dashboard, Prometheus, Grafana), see the
[Railway deployment guide](docs/railway-deployment.md) instead — it covers
all four services' setup, environment variables, and deploy commands in one
place.

## Executive Observability Dashboard (SPEC-7)

A cross-cutting capstone that evaluates and monitors the RAG Agent System
above — not a separate app. It reuses the real
`app/agent/prompts.py::SYSTEM_PROMPT` and `app/safeguards/masking.py::mask()`,
and its dashboard probes the real `app/` service's `/health` endpoint.

- `evaluation/` (SPEC-7.1) — clinical model comparison (`openai/gpt-4o-mini`
  vs. `openai/gpt-4o` via OpenRouter) against a fixed 15-question dataset,
  lexical metrics, an LLM judge, and clinical quality gates.
- `drift/` (SPEC-7.2) — deterministic monthly traffic simulation, SciPy K-S
  drift detection, and Evidently HTML reports.
- `cost/` (SPEC-7.3) — dated OpenRouter pricing, a 30-day cost projection,
  budget status, and quality-gated model-routing savings analysis.
- `dashboard/` (SPEC-7.4) — an authenticated FastAPI executive dashboard
  (`DASHBOARD_ACCESS_TOKEN` gates every route except `/metrics`) plus a
  Prometheus/Grafana stack charting live Chat API request rate, p95 latency,
  and error rate alongside the SPEC-7.1–7.3 quality/drift/cost evidence.
- `executive_summary.md`/`.pdf` (SPEC-7.5) — a one-page leadership brief
  citing every numerical claim to its exact source artifact and column.

Run each phase from the repository root (Windows PowerShell):

```powershell
# SPEC-7.1 - requires a real OPENROUTER_API_KEY in .env, even to replay a
# full results cache with zero paid calls (evaluation/.cache/results.jsonl).
.\.venv\Scripts\python.exe -m evaluation.run_evaluation

# SPEC-7.2 - deterministic, no external calls.
.\.venv\Scripts\python.exe -m drift.run_monthly_drift_reports

# SPEC-7.3 - deterministic, reads SPEC-7.1's evaluation output.
.\.venv\Scripts\python.exe -m cost.run_cost_analysis

# SPEC-7.4 - the authenticated dashboard alone.
$env:DASHBOARD_ACCESS_TOKEN="replace-with-at-least-16-characters"
.\.venv\Scripts\python.exe -m uvicorn dashboard.main:create_app --factory --host 127.0.0.1 --port 8001 --workers 1

# SPEC-7.5 - renders executive_summary.md to executive_summary.pdf via an
# isolated ReportLab environment; never touches requirements.txt.
uv run --with reportlab python scripts/render_executive_summary.py
```

Or bring up the full stack (chat API, dashboard, Prometheus, Grafana) with
`docker compose up --build` from the repository root — see
[dashboard/README.md](dashboard/README.md) for ports, required variables, and
failure-boundary details. All four services also run in production on
Railway as separate services (not via this Compose file) — see
[docs/railway-deployment.md](docs/railway-deployment.md) for the complete
setup, per-service environment variables, and troubleshooting. Generated
CSV/HTML/JSONL artifacts under `evaluation/`, `drift/`, and `cost/` are the
underlying evidence `executive_summary.md` cites; they are reproducible
from the commands above, not hand-authored.

## Orchestration and Grounding Decisions

- LangChain provides the agent and typed tool interface; LangGraph provides
  checkpointed state by `thread_id`.
- The agent exposes exactly two narrow tools to reduce tool confusion.
- LlamaIndex loads documents, creates sentence-aware chunks, and represents
  retrieved source nodes without an additional synthesis model.
- Qdrant Cloud performs managed embedding, storage, and semantic search and
  reuses a populated collection instead of duplicating ingestion.
- Retrieved nodes must share substantive normalized terms with the question.
  Unsupported retrieval returns exactly `Information not found.`
- Every retained policy or routing excerpt includes its source filename.

## Token Management

The local `llama3.2` model uses a 4,096-token context in the current setup.
`AGENT_HISTORY_TOKEN_BUDGET` defaults to 2,048 approximate tokens. Before each
model call, middleware keeps recent complete turns and reserves the remaining
context for the system prompt, tool schemas, retrieved evidence, and output.

The complete masked checkpoint remains in process while only the bounded slice
is sent to the model. Approximate counting is fast and model-independent, but
it is not identical to llama3.2's tokenizer.

## Abuse-Prevention Rate Limits

`POST /chat` is limited per client IP to 10 requests per rolling minute and
100 per rolling 24 hours by default. A blocked request returns HTTP 429 with a
`Retry-After` header before the agent or cloud model is called. Chainlit applies
the same limits per browser chat session before model use.

The limiter stores only salted hashes and timestamps in process memory. Its
counters reset on restart and are not shared across replicas; keep one Railway
worker or replace it with a shared Redis-backed limiter before scaling. Because
the UI is unauthenticated, a user can create a new browser session to obtain a
new UI allowance. Rate limiting reduces casual abuse but is not authentication
or DDoS protection.

## Privacy and Compliance Guardrails

The safeguards are designed to support principles in Kenya's
[Data Protection Act, 2019](https://new.kenyalaw.org/akn/ke/act/2019/24/eng@2022-12-31).
This implementation is a technical prototype, not a legal compliance
certification.

| Principle | AfyaPlus control |
|---|---|
| Data minimization | Supported phone numbers, emails, and member IDs are replaced before agent, model, memory, or tool processing. The request-local vault contains only values needed to restore that request's approved output. |
| Purpose limitation | The prompt and tool descriptions restrict processing to documented insurance verification, clinical routing, and clinician-supplied arithmetic. Diagnosis, prescribing, and dose selection are prohibited. |
| Security safeguards | Credentials stay in `.env`/deployment secrets; the vault is excluded from normal representations; unhandled failures return a generic 503 response. |

Additional controls:

- User and retrieved text are treated as untrusted data, not instructions.
- Unknown placeholders are never expanded.
- Knowledge claims require retrieved evidence and inline citations.
- Invalid calculator inputs return controlled errors instead of crashing.
- Uncertainty and clinical-risk decisions are escalated to qualified humans.
- Tests prove that supported raw PII does not reach the fake model boundary.

Regex masking does not detect every possible identifier or phone formatting
variation. Names, addresses, national IDs, and formatted numbers containing
spaces or hyphens require additional controls before real patient use. See the
[privacy documentation](docs/privacy.md) for the full threat model.

## Current Operational Limitations

- `/chat` and `/ui` have no authentication, authorization, or production
  audit sink. Only the separate SPEC-7.4 dashboard (`dashboard/`) is gated,
  by a shared `DASHBOARD_ACCESS_TOKEN`, not per-user identity or roles.
- Rate limiting is process-local; Chainlit limits are per session and can be
  bypassed by starting another unauthenticated session.
- The Chainlit UI remains unsuitable for real patient data without
  authentication and authorization.
- Conversation memory is process-local and is not shared across workers.
- Health checks report process liveness, not Ollama or Qdrant readiness.
- Local model quality and latency depend on host hardware.
- Human review remains required for clinical risk and benefits decisions.
- Docker Compose (`docker-compose.yml`) packages the chat API, dashboard,
  Prometheus, and Grafana for local/self-hosted use (SPEC-7.4). Production
  on Railway runs the same four services as separate Railway services
  (config-as-code under `app/railway.json` and `dashboard/railway/`), not
  this Compose file directly.
- No GitHub source is connected to any Railway service; every deploy is a
  manual `railway up`, so a passing CI run is not currently a deploy gate.

Do not expose this prototype to untrusted networks or process real patient data
without production security, privacy, retention, monitoring, and governance
controls.

## Foundational Triage Engine

The repository retains its original Week 1 triage prototype in `triage/`, with
`triage_cli.py` as its entrypoint. It calls a configured cloud model first,
falls back to local Ollama, validates strict JSON, and applies conservative
routing checks.

Its cloud settings are the `OPENROUTER_API_KEY` or `OPENAI_API_KEY` option,
`MODEL_BASE_URL`, and `CLOUD_MODEL` values in `triage/env.example` — its own
environment, independent of the RAG API's repo-root `.env.example` above.

Run it from the repository root after installing the shared requirements:

```text
python triage_cli.py --help
python triage_cli.py
python triage_cli.py "My chest hurts and I cannot breathe properly"
python triage_cli.py --simulate-cloud-failure "My child has a fever and is very weak"
```

Foundational component resources:

- [Triage engine documentation](triage/docs/triage_engine.md)
- [Sample outputs](triage/docs/triage_engine_sample_outputs.md)
- [Published slides](https://docs.google.com/presentation/d/e/2PACX-1vQD_5HJ-tt-xmST0p_DmFGOLQqflMh_aHLZffcVLEEQtt863cSO5jotVzHmZmXdOg-0SYz39J_Aqr5U/pub?start=false&loop=false&delayms=3000)
