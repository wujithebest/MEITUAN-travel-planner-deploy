# Dynamic Route Evaluation

This directory is reserved for dynamic route-planning evaluation. Fixed route snapshots under `backend/data/fixed_routes/` are UI demo assets and are excluded from all metrics here.

## Layout

- `cases/`: reviewed benchmark cases and their expected outcomes.
- `runs/<run_id>/`: complete, immutable artifacts from one evaluation run.
- `results/`: a convenient index of published summaries; it never replaces the source artifacts in `runs/`.

## Traceability requirements

Every live run must create `evaluation/runs/<YYYYMMDD-HHMMSS>-<short_id>/` and retain these files before any aggregate score is published:

- `manifest.json`: run ID, start/end time, Git commit, runner version, metric-spec version, case-set checksum, and safe runtime configuration. Secrets and API keys are never written.
- `cases_resolved.jsonl`: exact user input, profile, route context, expected labels, and order in which each case was executed.
- `raw_sse/<case_id>.txt`: unmodified SSE wire payload captured for the case.
- `events/<case_id>.jsonl`: parsed SSE events in time order, including status, `route_ready`, final `done`, error, and timeout events.
- `traces/<case_id>.json`: Hook output for stage timings, intent, dispatch decision, PlanReality result, final POIs, candidates, and terminal outcome.
- `responses/<case_id>.json`: normalized final response used by the scorer.
- `scores.jsonl`: field-level and case-level scoring evidence, including each matched or missed requirement.
- `summary.csv` and `summary.md`: derived metric tables only; each row links back to its case ID and source artifacts.
- `stop_report.json`: present for both completed and stopped runs; records the active stop rule, partial counts, and resumable remaining cases.
- `runner.log`: runner-side lifecycle log, retry/backoff decisions, and non-secret diagnostic messages.

Artifacts are append-only during a run. A rerun always gets a new run ID, so later results cannot overwrite or obscure an earlier result.

## Planned execution policy

- Run live requests serially (`concurrency=1`); never fan out calls to DeepSeek, Gaode, or Bocha.
- Start with a five-case pilot before a full batch.
- Record the end-to-end route generation time from request receipt to the final SSE `done` event.
- A constraint-aware fallback or an explicit infeasibility explanation is not an invalid result when the case labels allow it.
- Pause the batch and require review when any stop condition in `cases/benchmark_v1_draft.md` is met.

No runtime hook, request runner, or API call has been added or executed yet. The current contents are a review draft only.
