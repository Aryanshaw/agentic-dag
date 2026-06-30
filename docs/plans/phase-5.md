# Phase 5 Plan — API layer

## Files
- `api/routers/__init__.py`, `api/routers/deps.py` — `get_store` dependency (reads `app.state.db`; overridable in tests).
- `api/routers/runs.py` — `APIRouter`:
  - `POST /runs/execute/{graph_id}` body `{request}` → latest version → create run + one node_run per definition node → `step()` → return run state.
  - `GET /runs/{id}` → run + nodes (status/input/output/error) + logs.
  - `POST /nodes/{id}/retry` → assert `failed` (409 else); `incr_attempts`; `failed→pending`; `step()`.
  - `POST /nodes/{id}/approve` → assert `awaiting_approval`; `→done`; `step()`.
  - `POST /nodes/{id}/reject` body `{reason?}` → assert `awaiting_approval`; `→failed`; log reason; `step()` (reconciles run failed).
- `api/engine/store.py` — add `get_latest_version(graph_id)`.
- `api/main.py` — keep `Database` on `app.state.db`, include router, add CORS (client :3000).
- `api/tests/test_api.py` — httpx ASGITransport, override `get_store` with a temp-db store + seeded graph.

## Serialization
`run_to_dict(run)` → `{id, status, request, nodes:[{id,node_key,type,status,input,output,error,attempts,logs:[...]}]}`. FastAPI encodes datetimes.

## Test (`test_api.py`)
1. Execute an input-chain graph → 200, run `completed`, nodes present.
2. Retry precondition: retry a non-failed node → 409.
3. Approve resumes a parked run (approval seed) → `completed`.

## Gate
`pytest tests/test_api.py` green.
