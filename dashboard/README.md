# AfyaPlus Executive Observability Dashboard

This standalone FastAPI surface presents four executive controls from the
generated SPEC-7.1–7.3 evidence: live system health, feature quality, drift
vectors, and budget utilisation. It reads only sanitized artifacts and never
loads evaluation questions, model answers, or patient identifiers.

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

## Architecture and failure boundaries

- Startup fails on missing authentication, malformed URLs, or invalid/missing
  artifacts.
- Runtime health-probe failures become `UNKNOWN`; they do not crash rendering.
- The API exports bounded route/method/status-class metrics only. Messages,
  thread IDs, IP addresses, and patient identifiers are never metric labels.
- Metrics use one in-process registry per service, so both Python services
  deliberately run one Uvicorn worker.
- Grafana reads Prometheus through the private Compose service name and keeps
  its datasource and dashboard read-only/provisioned from Git.
- Prometheus should be network-restricted in production because `/metrics`
  exposes aggregate operational evidence without application-layer auth.
