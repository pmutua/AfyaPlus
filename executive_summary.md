# AfyaPlus Executive Evidence Brief

**Decision:** Approve controlled, quality-gated use of `openai/gpt-4o-mini`
for the evaluated AfyaPlus workflows. Do not treat simulation results or this
static brief as proof of production readiness or regulatory compliance.

## Executive Summary

AfyaPlus's generative layer passed clinical evaluation on `openai/gpt-4o-mini`
(15/15 questions, 7/7 quality gates, 100% grounding compliance) and is
projected to run at roughly one-tenth of a US cent per 30-day workload day
under the current mixed-model traffic assumption. The evaluated `openai/gpt-4o`
alternative failed the required grounding-compliance gate and is not eligible
for routing. Two systemic risks require engineering follow-up before wider
deployment: simulated quality drift appears by Month 3, and there is
currently no live production quality signal to confirm it does not also
occur with real traffic.

## Quality Performance Breakdown

- **Measured:** `openai/gpt-4o-mini` completed **15/15 questions**, passed
  **7/7 clinical gates**, scored **5.0000/5 overall**, and achieved **100%
  grounding compliance** [E1, E2]. In plain terms: every answer stayed
  faithful to the documented policy/clinical source, and no answer required
  a safety override.
- **Measured:** `openai/gpt-4o` completed **15/15 questions** but achieved
  only **93.33% grounding compliance** — one answer in fifteen was not fully
  supported by the retrieved reference — so it failed the required **100%**
  gate and is not eligible for cost-led routing [E1, E2].

## Cost & Efficiency Analysis

- **Measured:** Per-request cloud cost is **USD 0.00008024** for
  `gpt-4o-mini` versus **USD 0.00126867** for `gpt-4o` [E7].
- **Simulated:** The 30-day mixed-model workload contains **9,000 requests**
  and projects **USD 3.39612000 / KES 439.80**, consuming **94.34%** of both
  the daily and monthly budget caps and producing a **WARNING** status on
  each [E4].
- **Simulated:** All-mini routing preserves every recorded clinical gate and
  projects **USD 0.72216000** over 30 days, saving **USD 2.67396000
  (78.74%)** against the mixed baseline [E5].
- **Estimated (illustrative assumption, not measured):** A human-in-the-loop
  clinical reviewer, at an assumed **USD 30/hour** spending **2 minutes**
  validating each response, costs roughly **USD 1.00 per response** —
  four to five orders of magnitude more than either model's per-request
  cloud cost above. This is a planning illustration, not a costed staffing
  proposal: no human-in-the-loop review program currently exists in this
  system, and the assumed rate/throughput have not been validated against
  real AfyaPlus reviewer capacity.

## Systemic Operational Risks

- **Simulated:** Month 2 first detected operational drift of **+563.582 ms
  latency** and **+103.408 tokens** per request. Month 3 added actionable
  quality drift: ROUGE-L **-0.110996**, overall score **-0.594667**, and
  grounding compliance **-20 percentage points** versus reference [E3].
- **Live-only:** Current API health is intentionally not frozen into this
  report. The authenticated dashboard probes the real `/health` endpoint
  live and reports `UNKNOWN` when the service cannot be reached [E6].
- **Live-only:** The dashboard's exception counter (4xx/5xx responses on the
  real Chat API) is read live at request time, not simulated — it is
  intentionally absent from this static brief for the same reason [E6].

## Actionable Engineering Roadmap

- **Put safety before price** (clinical justification): retain the
  all-gates-pass requirement and route only to models that satisfy it, even
  though `gpt-4o` would otherwise be viable on cost alone.
- **Adopt `openai/gpt-4o-mini` for this evaluated scope** (financial
  justification): simulated all-mini routing preserves every recorded gate
  and saves **USD 2.67396000 (78.74%)** over 30 days against the mixed
  baseline [E5].
- **Treat any actionable quality-drift alert as a release hold** (safety
  justification): investigate, re-evaluate, and restore gate compliance
  before expanding traffic, rather than absorbing a Month-3-style quality
  regression silently.
- **Require human clinical and governance review before broader deployment**
  (compliance justification): these results do not establish legal
  compliance, patient safety in every scenario, or end-to-end production
  readiness.

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
  `daily_budget_usd`, `budget_utilization`, `budget_status`,
  `monthly_budget_usd`, `monthly_budget_utilization`, `monthly_budget_status`.
- **[E5]** `cost/structural_savings_analysis.csv` — columns `status`,
  `selected_model`, `quality_preserved`, `proposed_30d_usd`, `savings_usd`,
  `savings_percent`.
- **[E6]** `dashboard/health.py` — `probe_health`, `parse_exception_count`;
  `dashboard/README.md` — "Architecture and failure boundaries".
- **[E7]** `cost/cost_per_request_comparison.csv` — columns `model`,
  `average_cost_per_request_usd`.
