# Phase 6 Plan — Frontend debugger (minimal)

## Files
- `client/src/lib/api.ts` — tiny fetch helpers over `BaseURL` (constants.ts, :8000): `listGraphs`, `execute`, `getRun`, `retry`, `approve`, `reject`.
- `client/src/app/page.tsx` — one client page (`"use client"`).

## Page behaviour (LLD §10)
- On load: `GET /graphs` → pick first (seeded support graph), show its name.
- Submit form: textarea + Run → `POST /runs/execute/{graph_id}` with `{request:{text}}`.
- Run view: list node rows with status badge (color per status) + node_key + type.
- Click a node → side panel: input / output / error / ordered logs (JSON pretty).
- Buttons: Retry (when node failed), Approve / Reject (when awaiting_approval) → call endpoint, refresh.
- Poll `GET /runs/{id}` every 1s while a run is active.

## Style
Plain Tailwind + existing kit; no graph canvas (ReactFlow is future scope). Status colors:
done=green, skipped=gray, running=blue, failed=red, awaiting_approval=amber, pending=slate.

## Test
Manual: submit billing/bug/unclear requests, watch statuses, retry a failure, approve a pause.

## Gate
Page submits a request, shows live node statuses, inspects node I/O/logs, retry + approve work.
