# Phase 3 Plan — Deterministic handlers: branch, tool, approval

## Files
- `api/engine/mocks.py` — `mock_create_linear_issue(inp, idem_key)`, `mock_check_invoice(inp, idem_key)`. Dedupe on `idem_key` (partial-failure backstop); track distinct creations so tests can assert exactly one side-effect.
- `api/engine/handlers.py` — add `branch_handler`, `tool_handler`, `approval_handler`.
- `api/engine/registry.py` — register branch, tool, approval.
- `api/engine/store.py` — add `get_node_by_key(run_id, node_key)`.
- `api/tests/test_handlers.py`.

## Handlers
- **branch** (LLD §8): `label = inp["label"]`; for each outgoing edge whose `condition` ≠ label → `set_status(target, "skipped")`. Return `{"label": label}` → branch itself done.
- **tool** (LLD §7): re-fetch fresh node; if `output_json` set → log idempotent hit, return it (NO side-effect). Else `key=f"{run_id}:{node_key}"`, set idempotency_key, run mock keyed on it, `set_output` BEFORE return, return result. `config["tool"]` selects linear|invoice.
- **approval** (LLD §5): `set_status(node, "awaiting_approval")`, log, return None → executor leaves it parked → reconcile = awaiting_approval.

## Test (`test_handlers.py`)
1. Branch: billing request → bug & approval `skipped`, billing path `done`, final `done`, run `completed`.
2. Tool idempotency: call tool_handler twice on same node → identical output, exactly ONE created issue.
3. Approval: approval_handler parks node → status `awaiting_approval`.

## Gate
`pytest tests/test_handlers.py` green.
