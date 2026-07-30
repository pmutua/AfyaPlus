# AfyaPlus Executive Evidence Brief

**Decision:** Approve controlled, quality-gated use of `openai/gpt-4o-mini`
for the evaluated AfyaPlus workflows. Do not treat simulation results or this
static brief as proof of production readiness or regulatory compliance.

## Evidence boundary

- **Measured:** A live OpenRouter evaluation used the fixed AfyaPlus clinical
  dataset. `openai/gpt-4o-mini` completed **15/15 questions**, passed **7/7
  clinical gates**, scored **5.0000/5 overall**, and achieved **100% grounding
  compliance** [E1, E2].
- **Measured:** `openai/gpt-4o` completed **15/15 questions** but achieved
  **93.33% grounding compliance**, so it failed the required **100%** gate and
  is not eligible for cost-led routing [E1, E2].
- **Simulated:** Month 2 first detected operational drift of **+563.582 ms
  latency** and **+103.408 tokens** per request. Month 3 added actionable
  quality drift: ROUGE-L **-0.110996**, overall score **-0.594667**, and
  grounding compliance **-20 percentage points** versus reference [E3].
- **Simulated:** The 30-day mixed-model workload contains **9,000 requests**
  and projects **USD 3.39612000 / KES 439.80**, consuming **94.34%** of the
  daily budget cap and producing a **WARNING** status [E4].
- **Live-only:** Current API health is intentionally not frozen into this
  report. The authenticated dashboard probes the real `/health` endpoint and
  reports `UNKNOWN` when the service cannot be reached [E6].

## Leadership recommendation

- Put safety before price: retain the all-gates-pass requirement and route
  only to models that satisfy it.
- Prefer `openai/gpt-4o-mini` for this evaluated scope. Simulated all-mini
  routing preserves the recorded gates and projects **USD 0.72216000** over
  30 days, saving **USD 2.67396000 (78.74%)** against the mixed baseline [E5].
- Treat any actionable quality-drift alert as a release hold: investigate,
  re-evaluate, and restore gate compliance before expansion.
- Use the authenticated dashboard for live health, aggregate API metrics,
  drift, quality, and budget decisions. Keep Prometheus network-restricted.
- Require human clinical and governance review before broader deployment;
  these results do not establish legal compliance, patient safety in every
  scenario, or end-to-end production readiness.

## Source register

- **[E1]** `evaluation/model_comparison_summary.csv` — columns `model`,
  `total_questions`, `successful_questions`, `overall`,
  `all_gates_passed`.
- **[E2]** `evaluation/quality_gate_log.csv` — columns `model`, `gate`,
  `threshold`, `observed`, `passed`.
- **[E3]** `drift/drift_trend_table.csv` — columns `month`, `column`,
  `mean_change`, `drift_detected`, `requires_action`.
- **[E4]** `cost/cost_projection_30d.csv` — overall-row columns
  `projected_requests`, `projected_cost_usd`, `projected_cost_kes`,
  `daily_budget_usd`, `budget_utilization`, `budget_status`.
- **[E5]** `cost/structural_savings_analysis.csv` — columns `status`,
  `selected_model`, `quality_preserved`, `proposed_30d_usd`, `savings_usd`,
  `savings_percent`.
- **[E6]** `dashboard/health.py` — `probe_health`; `dashboard/README.md` —
  “Architecture and failure boundaries”.
