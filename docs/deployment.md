# AfyaPlus RAG Deployment Guide

## Deployment Architecture

The deployed RAG application uses three managed boundaries:

```text
Railway
  FastAPI + Chainlit + LangGraph + LlamaIndex orchestration
       |                         |
       | chat                    | managed embedding/search
       v                         v
  Ollama Cloud              Qdrant Cloud
```

Railway runs no embedding model and stores no vectors locally. Qdrant Cloud
Inference embeds knowledge chunks and questions, persists vectors, and performs
semantic search. Ollama Cloud supplies chat completion. Local Ollama remains an
optional development chat provider and fallback.

The current prototype uses only synthetic knowledge documents. It must not
process real patient data without the controls in [Privacy and Production
Readiness](#privacy-and-production-readiness).

## Required Services

- A Qdrant Cloud cluster with Cloud Inference enabled.
- An Ollama Cloud account and API key when `MODEL_PROVIDER=ollama_cloud`.
- A Railway service connected to this repository for hosted deployment.
- Python 3.11 or newer.

Qdrant documents the same managed `Document` inference flow used by AfyaPlus in
its [Cloud quickstart](https://qdrant.tech/documentation/cloud/quickstart-cloud/).
Railway provides an official [FastAPI deployment
guide](https://docs.railway.com/guides/fastapi).

## Environment Variables

Use `.env.example` for local development and `railway.env.example` as the
production variable checklist. Put real secrets only in the gitignored `.env`
for local use and in Railway's Variables section for deployment; never upload
either example file as a secret bundle.

### Chat

| Variable | Production value | Purpose |
|---|---|---|
| `MODEL_PROVIDER` | `ollama_cloud` | Select direct cloud chat |
| `OLLAMA_CLOUD_BASE_URL` | `https://ollama.com/v1` | OpenAI-compatible chat endpoint |
| `OLLAMA_CLOUD_MODEL` | An enabled cloud model | Chat and tool-calling model |
| `OLLAMA_CLOUD_API_KEY` | Secret | Ollama Cloud authentication |
| `CLOUD_TIMEOUT_SECONDS` | `30.0` | Chat request timeout |
| `AGENT_HISTORY_TOKEN_BUDGET` | `2048` | Approximate history sent per call |

Ollama documents direct cloud access and API-key authentication in its [Cloud
guide](https://docs.ollama.com/cloud). The application uses its documented
[OpenAI-compatible API](https://docs.ollama.com/api/openai-compatibility).

### Retrieval

| Variable | Production value | Purpose |
|---|---|---|
| `QDRANT_URL` | Cluster HTTPS endpoint | Managed vector database |
| `QDRANT_API_KEY` | Secret | Cluster authentication |
| `QDRANT_COLLECTION_NAME` | `afyaplus_knowledge_base` | Application-only collection |
| `QDRANT_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Managed dense model |
| `QDRANT_EMBEDDING_DIMENSIONS` | `384` | Model-compatible vector size |
| `QDRANT_TIMEOUT_SECONDS` | `30.0` | Qdrant request timeout |

Keep this collection dedicated to the AfyaPlus application. Model and dimension
changes require a new or rebuilt collection.

## Local Verification

Install dependencies before running checks:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
```

Verify the configured chat and Qdrant connections without printing keys:

```powershell
.\.venv\Scripts\python.exe scripts/verify_provider.py
```

The verification script opens or creates the configured Qdrant collection.
It does not ingest knowledge or send a sample chat request to Qdrant.

## Collection Lifecycle

The knowledge collection is initialized lazily on the first knowledge-tool
request:

1. The client connects with `cloud_inference=True`.
2. If the collection is absent, AfyaPlus creates a 384-dimensional cosine
   collection and records the embedding model as collection metadata.
3. LlamaIndex reads `knowledge/` and creates sentence-aware 512-token chunks
   with 64-token overlap.
4. Each chunk is uploaded as a Qdrant `Document`, so Qdrant generates the
   vector without local ML compute.
5. Only chunk text and `file_name` are stored as payload metadata.
6. A non-empty collection is reused on subsequent process starts.

Because a non-empty collection is treated as initialized, rebuild it after
changing source documents, chunking, model, or dimensions. Use a new collection
name for a reversible migration. Delete the old collection only after the new
one passes retrieval tests.

## Railway Production Deployment

The repository's `app/railway.json` selects Railpack, starts one Uvicorn worker on
Railway's injected `PORT`, gates activation on `/health`, and restarts failed
processes up to five times. `.python-version` keeps Railway and CI on Python
3.12, avoiding accidental runtime changes when Railpack defaults advance.

The production service belongs in the existing `afyaplus` project and
`production` environment. `railway.env.example` contains the complete required
key set. Configure these non-secret values in Railway:

| Variable | Value |
|---|---|
| `MODEL_PROVIDER` | `ollama_cloud` |
| `OLLAMA_CLOUD_BASE_URL` | `https://ollama.com/v1` |
| `CLOUD_TIMEOUT_SECONDS` | `30.0` |
| `AGENT_HISTORY_TOKEN_BUDGET` | `2048` |
| `QDRANT_COLLECTION_NAME` | `afyaplus_knowledge_base` |
| `QDRANT_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` |
| `QDRANT_EMBEDDING_DIMENSIONS` | `384` |
| `QDRANT_TIMEOUT_SECONDS` | `30.0` |
| `RATE_LIMIT_ENABLED` | `true` |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `10` |
| `RATE_LIMIT_REQUESTS_PER_DAY` | `100` |
| `RATE_LIMIT_TRUST_RAILWAY_PROXY` | `true` |
| `CHAINLIT_COT_MODE` | `hidden` |

Set `OLLAMA_CLOUD_MODEL`, `OLLAMA_CLOUD_API_KEY`, `QDRANT_URL`, and
`QDRANT_API_KEY` as Railway variables from an approved secret source. Never
copy their values into GitHub workflow files, `app/railway.json`, documentation,
or logs.

The effective start command is:

```text
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Create the service from `pmutua/AfyaPlus`, targeting the approved
production branch. Generate one Railway HTTPS domain after the first healthy
deployment. Do not add a volume: vectors remain in Qdrant, and conversation
memory is intentionally process-local.

`GET /health` proves only that the FastAPI process is alive. It does not test
Ollama or Qdrant readiness. Run `scripts/verify_provider.py` during controlled
deployment verification and exercise a synthetic grounded query after deploy.

Chainlit is mounted at `/ui` and uses WebSockets. Railway supports WebSockets
through the same public service, so no second process or port is required. Keep
the Uvicorn worker count at one while conversation checkpoints remain
in-memory; multiple workers can route successive socket or API turns to
different, isolated memory stores. Add a durable shared checkpointer and
session-affinity design before horizontal scaling.

The same one-worker constraint applies to rate limiting. API limits are keyed
by a salted hash of Railway's documented `X-Real-IP`; this header is trusted
only because `RATE_LIMIT_TRUST_RAILWAY_PROXY=true` is confined to the Railway
service. Chainlit limits are per generated browser session. Process restarts
clear all allowances, and replicas would maintain separate counters. Use a
shared Redis-backed limiter before scaling beyond one process.

Docker is no longer deferred: SPEC-7.4 added `app/Dockerfile`,
`dashboard/Dockerfile`, and a root `docker-compose.yml` for local use, plus
three additional Railway services (`dashboard`, `prometheus`, `grafana`)
running the same images in production. See
[railway-deployment.md](railway-deployment.md) for the complete four-service
setup, environment variables, and troubleshooting — this document covers
only the chat API's own Qdrant/Ollama Cloud configuration above.

## CI/CD Pipeline

`.github/workflows/ci.yml` runs for every pull request and for pushes to
`main` and `feat-rag-agent-system`. It installs `requirements.txt` before
running `pip check`, the complete pytest suite, compileall (now covering
`app scripts tests triage triage_cli.py evaluation drift cost dashboard`),
and the diff check. The workflow has read-only repository permissions and
cancels superseded runs on the same branch.

**Current state, stated plainly**: no Railway service has a GitHub source
connected. Every deploy — for all four services — is a manual `railway up`
(see [railway-deployment.md](railway-deployment.md)), so a passing CI run is
not currently a deploy gate. This is a known gap, not an oversight; closing
it would mean:

1. Connect each production service to its approved GitHub branch.
2. Enable **Wait for CI** in each service's GitHub deployment settings.
3. Keep automatic deployments enabled only for that branch.
4. Require the GitHub `Verify Python application` check before merging to
   the protected production branch.

With Wait for CI enabled, Railway would hold a deployment while GitHub
Actions runs, skip it when any workflow fails, and proceed only after all
checks succeed — avoiding a Railway API token in GitHub. Not yet done.

## Rollback

Use Railway's deployment history to select the last verified deployment and
choose **Redeploy**. A rollback reuses that deployment's code and configuration;
confirm its referenced variables still exist before activation. Then repeat the
health, docs, UI, and synthetic chat checks below. If a Qdrant schema or model
change caused the incident, restore the previously verified collection name
rather than deleting or rewriting the current collection in place.

For a bad Git commit, also revert it through the normal pull-request workflow.
Do not force-push the production branch or bypass CI to make the repository
history match the Railway rollback.

## Post-Deployment Checks

1. Confirm `GET /health` returns `200`.
2. Open `/ui/`, confirm the WebSocket session connects, and send a synthetic
   insurance-policy question.
3. Repeat a related question and confirm conversation context is retained.
4. Send a synthetic insurance-policy question through `POST /chat`.
5. Confirm grounded answers include tracked filename citations.
6. Ask an out-of-scope question and confirm `Information not found.` behavior.
7. Check Qdrant collection count and inference usage in the Cloud console.
8. Check application logs for sanitized provider/fallback warnings only.
9. Exceed the configured synthetic chat allowance and confirm HTTP 429 plus an
   integer `Retry-After` header without a model call.
10. Run the Postman scenarios in [manual-testing-postman.md](manual-testing-postman.md).

## Failure and Recovery

| Failure | Expected behavior | Operator action |
|---|---|---|
| Missing Qdrant configuration | Knowledge tool returns controlled unavailability | Correct Railway variables and redeploy |
| Qdrant timeout/outage | Retrieval fails without exposing credentials | Check cluster status, networking, and timeout |
| Chat provider failure | Configured fallback is attempted once when available | Review warning and provider health |
| Chainlit socket disconnect | UI reconnects or reports loss of connection | Check Railway service health and WebSocket path |
| HTTP 429 | Client exceeded a rolling allowance | Wait for `Retry-After`; investigate sustained abuse |
| Wrong model dimensions | Qdrant rejects incompatible vectors | Use a compatible collection or rebuild |
| Stale knowledge | Existing collection continues serving old chunks | Build and verify a new collection name |

Never log `.env`, API keys, authorization headers, request bodies, the privacy
vault, or full model messages.

## Privacy and Production Readiness

Qdrant Cloud and Ollama Cloud are external processors. Supported PII in user
messages is masked before tool or model processing, but retrieved knowledge is
sent to Qdrant during ingestion and tool results are sent to the chat provider.

The free Qdrant embedding models are US-hosted even when a cluster is in
another region; consult the current [Qdrant Cloud Inference region
documentation](https://qdrant.tech/documentation/cloud/inference/). Synthetic
capstone data is acceptable for this architecture. Before real PHI or patient
records are used:

- obtain legal and security approval for every processor and feature;
- confirm applicable contracts/BAAs and data-processing regions in writing;
- expand PII detection beyond the prototype patterns - see
  [privacy.md](privacy.md)'s "Not Currently Masked" section for the specific
  gap (names, National ID, KRA PIN, addresses, and why this needs more than
  just adding regex patterns);
- add authentication, authorization, audit logging, retention, and deletion;
- protect both Chainlit WebSockets and FastAPI routes with the selected access
  controls;
- add encryption, key rotation, readiness monitoring, backups, and incident
  response;
- run retrieval-quality, privacy, prompt-injection, and dependency reviews.

See [privacy.md](privacy.md) and
[deployment-architecture-research.md](deployment-architecture-research.md) for
the complete boundary and decision rationale.

## Official References

- [Qdrant Cloud quickstart](https://qdrant.tech/documentation/cloud/quickstart-cloud/)
- [Qdrant Cloud Inference](https://qdrant.tech/documentation/cloud/inference/)
- [Ollama Cloud](https://docs.ollama.com/cloud)
- [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
- [Railway FastAPI guide](https://docs.railway.com/guides/fastapi)
- [Railway variables](https://docs.railway.com/variables)
- [Railway health checks](https://docs.railway.com/deployments/healthchecks)
- [Chainlit FastAPI integration](https://docs.chainlit.io/integrations/fastapi)
- [Chainlit deployment and WebSockets](https://docs.chainlit.io/deploy/overview)
