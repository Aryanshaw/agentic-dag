# Phase 2 Plan — Executor core + state machine + input handler

## Files
- `api/engine/registry.py` — `REGISTRY: dict[str, handler]`. Phase 2 registers only `input`.
- `api/engine/handlers.py` — `input_handler(node, inp, store)`: seeds shared state, returns run.request (spread so handles like `text` resolve, plus `request` key). Always → done.
- `api/engine/executor.py` — `step(run_id, store)` readiness loop + `reconcile_run_status(run_id, store)`.
- `api/engine/store.py` — add `get_definition(run_id)` (join run→graph_version, return definition dict).
- `api/tests/test_executor.py`.

## step() loop (LLD §4)
- Load definition edges once. Loop: reload nodes → `by_key={node_key:node}` → ready = pending nodes whose deps all in (done|skipped) → if none break.
- Per ready node: build_input, set_input, set_status running, log start, run handler. Re-fetch node: if still `running` (handler didn't park/skip itself) → set_output(out) + set_status done. On exception → set_error, set_status failed, log error.
- Missing registry type → raise inside try → node failed.
- End: `reconcile_run_status`, return refreshed run.

## reconcile_run_status
any failed → `failed`; elif any awaiting_approval → `awaiting_approval`; elif all terminal (done|skipped) → `completed`; else `running`.

## Test (`test_executor.py`)
1. Input chain a→b→c (all type input): step → all `done`, run `completed`.
2. Gating + terminal: a(input)→b(unknown type)→c(input): a done, b failed, c never runs (stays `pending`), run `failed`.

## Gate
`pytest tests/test_executor.py` green.
