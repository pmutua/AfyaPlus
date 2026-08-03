# Operations Runbook

Day-to-day operation of the deployed AfyaPlus system: what to check, how
often, what a bad reading means, and what to do about it. This is separate
from [deployment.md](deployment.md) and
[railway-deployment.md](railway-deployment.md), which cover *getting
services deployed*, not *running them afterward*.

## 1. Quick daily/routine check (5 minutes)

1. Open the Grafana dashboard
   ([grafana-production-593c.up.railway.app](https://grafana-production-593c.up.railway.app/login),
   or `http://localhost:3000` locally) and look at the **System Health**
   panel — should read green/`1`.
2. Check **Chat API Error Rate** — should be green (under 2%).
3. Check **Chat API p95 Latency** — compare against your own sense of
   normal; there's no fixed SLA target defined yet (see section 6, open item).
4. If anything is red, jump to section 4 (incident response) for that panel.

That's it for a routine check. Sections below cover the less-frequent,
more-involved operational work.

## 2. Grafana panel reference

| Panel | Metric | Meaning | Healthy | Warning | Bad |
|---|---|---|---|---|---|
| System Health | `afyaplus_upstream_health` | Chat API's real `/health` endpoint, probed live | `1` (green) | — | `0` (red) |
| Chat API Request Rate | `rate(...http_requests_total{route="/chat"}[5m])` | Traffic volume | Informational, no threshold | — | — |
| Chat API p95 Latency | `histogram_quantile(0.95, ...duration_seconds...)` | 95th-percentile response time | Informational, no fixed threshold set | — | — |
| Chat API Error Rate | 4xx and 5xx requests as a share of total `/chat` requests, 5-minute window | Live error rate | under 2% (green) | 2-5% (orange) | 5% or more (red) |
| Feature Quality Matrix | `afyaplus_feature_quality_score{metric="overall"}` | Last evaluation run's overall score, 1-5 scale (5 = best) | 4.0 or higher (matches the SPEC-7.1 gate threshold in `evaluation/quality_gates.py`) | — | below 4.0 — but read the value yourself: this panel is a plain gradient bar with no threshold coloring configured in Grafana, unlike the other rows here |
| Drift Vector Status | `afyaplus_drift_detected`, `afyaplus_drift_action_required` | Whether the last drift simulation flagged a column | `0` (green) | — | `1` (red) |
| Budget Capital Utilisation | `afyaplus_budget_utilization_ratio` | Last cost projection's % of the daily budget cap | under 80% (green) | 80-95% (orange) | 95% or more (red) |
| Projected 30-Day Cost | `afyaplus_projected_30d_cost_usd` | Last cost projection's raw USD figure | Informational, no fixed threshold | — | — |

**Critical caveat, read before trusting any of the bottom five rows**: the
Feature Quality Matrix, Drift Vector Status, Budget Capital Utilisation, and
Projected 30-Day Cost panels are **not live** — `dashboard/main.py` loads
the underlying CSVs once, at process startup (`create_app()` calls
`publish_artifacts()` exactly once), and never re-reads them. They show
whatever `evaluation/`, `drift/`, and `cost/` produced **the last time the
`dashboard` service was built and deployed** — potentially stale by days or
weeks, not a rolling live measurement. Only **System Health** is refreshed
per-request (and only when something actually loads the dashboard's `/`
page — Prometheus scraping `/metrics` does not trigger a fresh probe; if
nobody opens the dashboard for a while, System Health also goes stale at
its last-known value).

To get fresh numbers into these four panels, you must re-run the relevant
pipeline **and** redeploy the `dashboard` service (see section 3) — there is no
way to refresh them without a redeploy.

## 3. Re-running the evaluation / drift / cost pipelines

None of these three pipelines run on a schedule or ingest live production
traffic today — they are point-in-time analyses you trigger manually, and
two of the three (drift, cost) currently operate on **simulated** data, not
real usage. Know which is which before treating a result as ground truth:

| Pipeline | Data source | Real spend? |
|---|---|---|
| `evaluation/` (SPEC-7.1) | Real OpenRouter API calls against a fixed 15-question dataset | **Yes** — real money per run, though a full results cache replays with zero new calls |
| `drift/` (SPEC-7.2) | Deterministic simulation seeded from `evaluation/`'s own output | No |
| `cost/` (SPEC-7.3) | Deterministic 30-day projection built from a fixed workload assumption, using dated real OpenRouter pricing | No (it's a projection, not a bill) |

### When to re-run

- **`evaluation/`**: after any change to the system prompt
  (`app/agent/prompts.py`), the knowledge base, or the set of models being
  compared. Not on a fixed calendar cadence — re-run when something that
  could affect answer quality actually changed. Real cost each time unless
  the cache already has every `(model, question_id)` pair.
- **`drift/`**: after re-running `evaluation/`, if you want the drift
  simulation's "reference" window to reflect the latest evaluation
  numbers. Free to re-run as often as you like otherwise — it's
  deterministic and reproduces the same output for the same input.
- **`cost/`**: after `evaluation/` changes which model(s) pass the quality
  gates (since routing recommendations depend on that), or after a real
  OpenRouter pricing change (the pricing table in `cost/pricing.py` is
  dated and needs a manual update if provider prices move).

### Commands

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_evaluation
.\.venv\Scripts\python.exe -m drift.run_monthly_drift_reports
.\.venv\Scripts\python.exe -m cost.run_cost_analysis
```

### Getting the new numbers into Grafana

Re-running the scripts above only updates the CSV files on your local
disk. The Railway `dashboard` service won't see them until you rebuild and
redeploy it (its Dockerfile copies the CSVs in at build time):

```powershell
railway up --service dashboard --detach
railway redeploy --service dashboard --yes
```

See [railway-deployment.md section 5](railway-deployment.md#5-the-deploy-recipe)
if this fails on the first `up` — that's expected, the `redeploy` after it
is what actually applies the change.

## 4. Incident response

| Symptom | Likely cause | What to do |
|---|---|---|
| System Health panel red | Chat API down, or its `/health` route unreachable from the dashboard's private network | `railway logs --service afyaplus-rag-agent --latest --lines 50`; check for a crash or a bad env var. Redeploy if it crashed on a bad config change. |
| Chat API Error Rate red | A dependency (Ollama Cloud or Qdrant) is failing, or a bad deploy went out | Check `railway logs --service afyaplus-rag-agent --latest` for the actual exception category (never raw exception details reach the client, but logs have it). Roll back via Railway's deployment history if a recent deploy caused it — see [deployment.md Rollback section](deployment.md#rollback). |
| Budget Capital Utilisation red (95% or more) | The last cost projection is close to/over the daily cap | This is a **projection**, not live billing — check the real provider console (OpenRouter) for actual spend before panicking. If real spend is genuinely high, see `cost/structural_savings_analysis.csv` for the quality-gated cheaper-model routing recommendation already computed. |
| Drift Vector Status red | The last drift simulation flagged a column as drifted | This is **simulated**, not live traffic — it does not mean production quality has actually degraded. Treat it as a prompt to re-run `evaluation/` against current conditions and see if real quality gates still pass, not as a live incident. |
| Feature Quality Matrix below 4.0 | The last evaluation run's overall score dropped | Check `evaluation/quality_gate_log.csv` for which specific gate(s) failed. If a prompt/knowledge-base change caused it, that change should not go to production until gates pass again. |
| Prometheus target down (visible in Grafana's own "Data source" health, or a panel showing "No data") | The `afyaplus-rag-agent` or `dashboard` service is down, or its `/metrics` route is failing | Check the target service directly first (`railway logs --service <name> --latest`). Prometheus itself rarely needs restarting — check what it's *trying* to scrape before assuming Prometheus is broken. |
| Grafana shows no data at all / can't load | Grafana can't reach Prometheus over the private network, or Grafana itself crashed | `railway logs --service grafana --latest --lines 30`. Confirm Prometheus is actually up first (`railway deployment list --service prometheus --json`). |
| Dashboard returns 401/403 | Wrong or missing `DASHBOARD_ACCESS_TOKEN` | Use the `X-Dashboard-Token` header (not the query param, for anything beyond a quick manual check) — see [dashboard/README.md](../dashboard/README.md). |

For chat-API-specific failure modes beyond these (Qdrant timeout, provider
fallback, rate limiting), see the existing table in
[deployment.md's Failure and Recovery section](deployment.md#failure-and-recovery)
— not duplicated here.

## 5. Secret rotation

Rotate a key whenever it may have been exposed (e.g. accidentally printed
to a terminal transcript, committed, or shared) — see the standing note in
this project's own history where two keys were flagged for rotation after
an accidental print during a Railway config inspection.

1. Generate a new value in the provider's own console:
   - **`OLLAMA_CLOUD_API_KEY`**: Ollama Cloud console.
   - **`QDRANT_API_KEY`**: Qdrant Cloud console, for the specific cluster.
   - **`DASHBOARD_ACCESS_TOKEN`** / **`GRAFANA_ADMIN_PASSWORD`**: these
     aren't rotated at a provider — just generate a new random string
     yourself (see [railway-deployment.md section 3](railway-deployment.md#3-per-service-environment-variables)
     for the PowerShell one-liner).
2. Set the new value on the relevant Railway service:
   ```powershell
   railway variable set "KEY=new-value" --service <name> --skip-deploys
   ```
3. Revoke/delete the *old* key at the provider console, if the provider
   supports it, once you've confirmed the new one works.
4. Redeploy the affected service so it picks up the new value:
   ```powershell
   railway redeploy --service <name> --yes
   ```
5. Verify: for the chat API, send a real chat request and confirm a
   grounded answer still comes back; for the dashboard/Grafana, confirm
   login/token access still works with the new value.

## 6. Known open gaps (don't assume these exist)

- No alerting is configured — Grafana's thresholds are visual only (a red
  panel), nothing pages anyone. Checking the dashboard is currently a
  manual, human action (section 1), not an automated one.
- No fixed p95 latency SLA/threshold is defined for the Chat API Request
  Rate/Latency panels — they're informational only today.
- No scheduled/automatic re-run of `evaluation/`, `drift/`, or `cost/` —
  everything in section 3 is manually triggered.
- No log aggregation — `railway logs` against each service individually is
  the only way to see application logs; there's no centralized search
  across all four services.

These match the same honestly-stated gaps in
[architecture.md's Future Scaling Priorities](architecture.md#future-scaling-priorities) —
this runbook describes how to work within today's actual capabilities, not
a target state that doesn't exist yet.
