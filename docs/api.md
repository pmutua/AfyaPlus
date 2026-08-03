# AfyaPlus RAG Agent API

## Run Locally on Windows

From the repository root, create and activate the project virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `QDRANT_URL` and `QDRANT_API_KEY` in the gitignored `.env`. Never copy a
real key into `.env.example`.

The first grounded knowledge request may take longer because it creates and
populates an empty Qdrant collection. Later requests reuse the process-level
retriever and persisted collection. See [deployment.md](deployment.md) for
collection lifecycle and Railway configuration.

When using the default `MODEL_PROVIDER=ollama_local`, install Ollama separately
and ensure the local chat model is available. Cloud-only deployments can skip
this step:

```powershell
ollama pull llama3.2
ollama list
```

Ollama commonly runs as a Windows background service. If
`http://127.0.0.1:11434` is already listening, do not start a second
`ollama serve` process.

Start the application:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Interactive OpenAPI documentation is available at
`http://127.0.0.1:8000/docs`; the raw schema is at `/openapi.json`.

## Chainlit Browser Chat

Open `http://127.0.0.1:8000/ui/` to chat without constructing API requests.
Chainlit is mounted inside the same FastAPI process and calls the same
`run_chat()` service as `POST /chat`; it does not call Ollama, Qdrant, or the
agent directly.

Each new browser conversation receives a generated `ui-<uuid>` thread ID.
Messages in that conversation reuse the ID for LangGraph memory, while a new
conversation receives an isolated history. The UI uses a WebSocket connection
and returns a generic message if the agent is unavailable.

## `GET /health`

Returns process liveness:

```json
{
  "status": "ok"
}
```

Status: `200 OK`.

This endpoint does not query Ollama or Qdrant, so it is not a dependency
readiness check.

## `GET /metrics`

Prometheus exposition format. Exports bounded-cardinality counters/histograms
for completed requests, request duration, and in-progress requests, labeled
only by `method`, `route` (from a fixed allowlist), and `status_class` — never
by message content, thread IDs, or IP addresses. Added in SPEC-7.4
(`app/observability.py`); intentionally unauthenticated so Prometheus can
scrape it over Railway's private network. See
[railway-deployment.md](railway-deployment.md) for how this is scraped in
production.

## `POST /chat`

Submits one conversation turn.

### Request

```json
{
  "message": "Check member AP-123456 maternity waiting-period policy.",
  "thread_id": "demo-session-001"
}
```

| Field | Type | Validation | Meaning |
|---|---|---|---|
| `message` | string | Trimmed, 1-8,000 characters | User question or permitted calculation request |
| `thread_id` | string | Trimmed, 1-128 characters, letters/digits/`_`/`-` only | Non-PII conversation key |

Do not place a phone number, email address, member ID, name, or other personal
identifier in `thread_id`. Unlike `message`, the thread ID is a routing key and
is not passed through the masking function.

### Success Response

```json
{
  "response": "Member AP-123456 is subject to the documented policy. [Source: insurance_verification_policy.txt]",
  "thread_id": "demo-session-001"
}
```

Status: `200 OK`. The exact natural-language answer depends on the request,
retrieved evidence, tool calls, and local model.

### Privacy Behavior

Supported phone numbers, emails, and AfyaPlus IDs in `message` are replaced by
typed placeholders before the agent and model receive the text. If the final
answer includes one of the current request's placeholders, the API restores
the original value immediately before returning the response.

The API never returns the placeholder vault. Unknown placeholders are not
expanded. See [privacy.md](privacy.md) for the complete boundary and known
limitations.

### Conversation Behavior

Reuse the same `thread_id` for related turns. LangGraph stores masked history
in process-local memory and isolates it by thread ID. A process restart clears
history. Multiple application workers do not share history.

Only recent complete turns, bounded by `AGENT_HISTORY_TOKEN_BUDGET`, are sent
to the model on each call. The complete in-process checkpoint remains until
the process ends.

### Validation Error

Malformed JSON, missing fields, empty values, messages longer than 8,000
characters, or invalid thread IDs produce FastAPI's `422 Unprocessable Entity`
response with validation details.

Example invalid request:

```json
{
  "message": "Habari",
  "thread_id": "contains spaces"
}
```

### Service Error

An unhandled agent or model failure produces:

```json
{
  "detail": "The AfyaPlus assistant is temporarily unavailable."
}
```

Status: `503 Service Unavailable`.

The knowledge tool handles its own retrieval exceptions and normally returns
a temporary-unavailability tool result to the agent instead of propagating an
exception to the API.

Qdrant configuration errors, inference failures, and network timeouts follow
that same controlled knowledge-tool failure path. Client responses never
include the configured endpoint key or provider exception details.

### Rate-Limit Error

`POST /chat` is limited per client IP before request content reaches the agent.
The default rolling limits are 10 requests per minute and 100 per 24 hours.
An exceeded limit produces:

```json
{
  "detail": "Too many requests. Try again in 60 seconds."
}
```

Status: `429 Too Many Requests`. The integer `Retry-After` response header
contains the minimum wait in seconds. `/health`, `/docs`, and static UI traffic
do not consume chat allowances. Chainlit message submissions use the same
limits per generated browser-session ID rather than IP because the
unauthenticated Chainlit message hook has no trustworthy client address.

## Example PowerShell Request

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

## Current Operational Boundaries

The API and Chainlit UI are a capstone prototype. They currently have no
authentication, authorization, durable/distributed memory, or production audit
sink. Rate-limit counters reset on restart, are not shared across replicas, and
the per-session UI limit can be bypassed by starting another session. Do not
submit real patient data without adding the remaining production controls.
