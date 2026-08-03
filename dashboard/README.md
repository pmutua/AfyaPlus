# AfyaPlus Executive Observability Dashboard

This standalone FastAPI surface presents four executive controls from the
generated SPEC-7.1–7.3 evidence: live system health, feature quality, drift
vectors, and budget utilisation. It reads only sanitized artifacts and never
loads evaluation questions, model answers, or patient identifiers.

**Feature quality is a summary, not every SPEC-7.1 metric.** `evaluation/`
computes BLEU-4, ROUGE-1/2/L, token F1, and four individual LLM-judge
dimensions (correctness, groundedness, relevance, helpfulness) per answer —
but this dashboard and its matching Grafana panel only ever surface
`rouge_l` and the judge's blended `overall` score per model/feature
(`dashboard/data_sources.py::_quality_row()`). The rest exist only in
`evaluation/full_evaluation_results.csv` and `llm_judge_matrix.csv`,
reachable through the [evidence-file viewer](#evidence-file-viewer) below,
not through any chart.

## Run locally on Windows

From the repository root:

```powershell
$env:DASHBOARD_ACCESS_TOKEN="replace-with-at-least-16-characters"
.\.venv\Scripts\python.exe -m uvicorn dashboard.main:create_app --factory --host 127.0.0.1 --port 8001 --workers 1
```

Open `http://127.0.0.1:8001/?access_token=<token>`. Automation should prefer
the `X-Dashboard-Token` header because query values may be retained in browser
history or proxy logs. `/metrics` intentionally remains unauthenticated for
the private Prometheus scrape network.

## Evidence-file viewer

`GET /artifacts` lists the raw evidence behind every panel and every
`executive_summary.md` claim; `GET /artifacts/{path}` serves one file. Both
inherit the same `DASHBOARD_ACCESS_TOKEN` auth as every route except
`/metrics`.

Deliberately not a general file browser: `dashboard/artifacts.py` allowlists
exactly 14 relative paths (the SPEC-7.1-7.3 CSVs/JSONL, the three drift HTML
reports, and `executive_summary.md`/`.pdf`), since `DASHBOARD_ARTIFACT_ROOT`
in production is the whole app container (`/app`), including source code.
The allowlist check runs on the raw requested string before any filesystem
resolution, plus a resolved-path containment check as defense-in-depth
against traversal.

Authentication accepts, in priority order: the `X-Dashboard-Token` header, an
`HttpOnly`/`SameSite=Strict` session cookie, or the `?access_token=` query
parameter. The first request that authenticates via query param gets the
cookie set automatically (1-hour `Max-Age`, `Secure` when served over HTTPS)
so the token never has to appear in a second URL for the rest of that browser
session — avoiding repeated exposure via proxy/access logs and browser
history. Header auth (the automation path) never touches the cookie. Every
authenticated response also gets `Referrer-Policy: no-referrer`.

Served HTML artifacts (the drift reports) get
`Content-Security-Policy: sandbox allow-scripts` and
`X-Content-Type-Options: nosniff` — same-origin HTML is a stored-XSS surface
even when the content is code-generated rather than user-authored; the
sandbox blocks cookie/localStorage access, top-level navigation, and popups
from the served page while keeping the reports' interactive charts working.

## Run the observability stack

Set `DASHBOARD_ACCESS_TOKEN` and `GRAFANA_ADMIN_PASSWORD`, then run:

```powershell
docker compose up --build
```

The chat API is available on port 8000, the executive dashboard on port 8001,
Prometheus on port 9090, and Grafana on port 3000. Compose runs the API against
hosted Ollama Cloud and loads its cloud model/key plus Qdrant credentials from
the ignored `.env`. Compose injects only the API's required variables, not the
dashboard, Grafana, or evaluation secrets. It does not host an LLM or depend
on a local Ollama daemon.

Grafana requires `GRAFANA_ADMIN_USER` (default `admin`) and the required
`GRAFANA_ADMIN_PASSWORD`; anonymous access and sign-up are disabled. Its
Prometheus datasource and AfyaPlus executive dashboard are provisioned from
the version-controlled files under `dashboard/grafana/`.

## Deploying to Railway instead of Compose

Live: [dashboard-production-743b.up.railway.app](https://dashboard-production-743b.up.railway.app)
(token-gated) and [grafana-production-593c.up.railway.app](https://grafana-production-593c.up.railway.app/login)
(login-gated). The chat API these probe is at
[afyaplus-rag-agent-production.up.railway.app](https://afyaplus-rag-agent-production.up.railway.app).
Prometheus has no public URL by design (private-network only). These are
per-deployment Railway domains, not permanent — reconfirm with `railway
status` if a service is ever recreated.

All four services (chat API, dashboard, Prometheus, Grafana) also run in
production as separate Railway services — Railway does not run
`docker-compose.yml` directly, so each needs its own build config and
private-network wiring. See
[docs/railway-deployment.md](../docs/railway-deployment.md) for the
complete setup, per-service environment variable tables, the exact deploy
commands, and a troubleshooting section covering every real issue hit while
setting this up (path-mangling on Windows, healthcheck/PORT gotchas, and
more). Once deployed, see
[docs/operations-runbook.md](../docs/operations-runbook.md) for what each
Grafana panel means and how to respond when one goes red — including the
important caveat that the quality/drift/cost/budget panels are snapshots
from the dashboard's last deploy, not live-refreshed.

## Architecture and failure boundaries

- Startup fails on missing authentication, malformed URLs, or invalid/missing
  artifacts.
- `/artifacts` serves only the explicit 14-path allowlist in
  `dashboard/artifacts.py`, never a general file browser — see "Evidence-file
  viewer" above.
- Runtime health-probe failures become `UNKNOWN`; they do not crash rendering.
- The API exports bounded route/method/status-class metrics only. Messages,
  thread IDs, IP addresses, and patient identifiers are never metric labels.
- Metrics use one in-process registry per service, so both Python services
  deliberately run one Uvicorn worker.
- Grafana reads Prometheus through a private network name (Compose service
  name locally, `prometheus.railway.internal` on Railway) and keeps its
  datasource and dashboard read-only/provisioned from Git.
- Prometheus should be network-restricted in production because `/metrics`
  exposes aggregate operational evidence without application-layer auth.
