# Spec: Agentic DAG Workflow Engine

Companion to [HLD.md](./HLD.md) · [LLD.md](./LLD.md) · [flow.md](./flow.md).
This spec is the build contract: phased, each phase says **what / how / how-to-test**.
Final phase = the complete DAG engine with all 5 scenario tests green.

---

## Objective

Build a backend DAG workflow engine with agent-style decision nodes. A run executes a
graph of typed nodes (input, agent, branch, tool, approval), persists every node's state
and trace, gates execution on dependencies, branches on an LLM decision, pauses for human
approval, retries failed nodes, and makes tool side-effects idempotent. A thin Next.js
debugger drives and inspects runs.

**Success = all 5 scenarios pass:** branching, retry, approval, validation-failure,
idempotency (see Success Criteria).

## Tech Stack

| Concern | Choice |
|---------|--------|
| API | FastAPI (async) |
| DB | SQLAlchemy 2.0 async + SQLite (`aiosqlite`), Alembic migrations |
| Validation | Pydantic v2 |
| Agent LLM | **Groq SDK · Llama 3.3 70B** (`llama-3.3-70b-versatile`) |
| Tests | pytest + pytest-asyncio + httpx |
| Frontend | Next.js debugger (existing kit) |
| Execution | inline-await `step()` per request; no queue/worker/daemon |

## Commands

```bash
# add deps
uv --directory api add groq pytest pytest-asyncio httpx
# migrate
uv --directory api run alembic upgrade head
uv --directory api run alembic revision --autogenerate -m "msg"
# run
pnpm dev:api          # api  :8080
pnpm dev:client       # ui   :3000
# test
uv --directory api run pytest -q
uv --directory api run pytest api/tests/test_scenarios.py -q   # the 5 acceptance scenarios
```

## Project Structure

```
api/
  models.py                 → SQLAlchemy tables (graphs, graph_versions, runs, node_runs, node_logs)
  engine/
    schemas.py              → Pydantic contracts (Classification, etc.)
    graph.py                → deps_of, is_dag, build_input
    store.py                → persistence interface + impl (only SQL touchpoint)
    registry.py             → type → handler map
    handlers.py             → the 5 node handlers
    executor.py             → step() loop + reconcile_run_status
  agent/
    classify.py             → Groq call + Pydantic validation (Phase 4)
  seeds/
    support_graph.json      → the assignment workflow {nodes, edges}
  routers/
    runs.py                 → execute / get / retry / approve / reject
  tests/
    test_graph.py · test_executor.py · test_handlers.py · test_scenarios.py
client/                     → debugger UI (Need reactflow integration in future to display graphs visually for user ease and execute it) (submit · statuses · inspect · retry · approve)
```

## Code Style

Async throughout. Handlers are pure-ish: take input, return dict, raise on failure. No SQL
outside `store.py`.

```python
async def tool_handler(node: NodeRun, inp: dict, store: Store) -> dict:
    if node.output_json is not None:                 # idempotent replay
        await store.log(node.id, "info", "idempotent hit")
        return node.output_json
    key = f"{node.run_id}:{node.node_key}"
    result = mock_create_linear_issue(inp, idem_key=key)
    await store.set_output(node.id, result)          # persist before return
    return result
```

Conventions: `snake_case` Python; node statuses are string literals; enums via `Literal[...]`
in Pydantic; one handler per node type, registered in `REGISTRY`.

## Testing Strategy

- **Unit** (`test_graph.py`): `is_dag` accepts DAG / rejects cycle; `deps_of`, `build_input`.
- **Engine** (`test_executor.py`): readiness gating + terminal reconcile, tested on a real `input`-node chain.
- **Handler** (`test_handlers.py`): idempotency, branch-skip, validation-fail, approval park.
- **Scenario** (`test_scenarios.py`): the 5 acceptance scenarios end-to-end through the API.
- Agent scenarios hit **real Groq** with unambiguous inputs (e.g. "I was double-charged" →
  billing). Validation-failure is tested by feeding the **real** `Classification` validator a
  malformed payload — a real code path, not a mock. No stubs, no monkeypatching: if a test is
  hard to write, the code is wrong, not the test.

## Boundaries

- **Always:** run `pytest` before declaring a phase done; keep SQL inside `store.py`; persist
  tool output before returning; validate agent output before downstream runs.
- **Ask first:** adding a dependency beyond those listed; schema changes after Phase 0;
  changing the seed graph shape.
- **Never:** commit `GROQ_API_KEY`; let a tool side-effect run without the idempotency guard;
  build the product-future scope (board builder, versioning UI, multi-tenant, queue/workers).

---

## Phased Plan

Each phase is independently testable and builds on the prior. Do not advance until the
phase's test passes.

### Phase 0 — Foundations: schema + store
**Build:** `models.py` (5 tables per LLD §1), Alembic migration, `store.py` interface
(`get_run`, `get_nodes`, `create_run`, `set_status`, `set_output`, `log`) + SQLite impl.
**How:** SQLAlchemy async models; `aiosqlite` URL; autogenerate migration.
**Test:** `alembic upgrade head` succeeds; a test inserts a run + node_run and reads it back;
`set_status` enforces allowed transitions (reject `done → running`).

### Phase 1 — Graph primitives
**Build:** `graph.py`: `deps_of(node_key, edges)`, `is_dag(nodes, edges)` (Kahn), 
`build_input(node_key, edges, nodes)`.
**How:** pure functions over the definition JSON; no DB.
**Test:** `test_graph.py` — linear + branching graph give correct deps; a cyclic graph fails
`is_dag`; `build_input` maps `sourceHandle → targetHandle` correctly.

### Phase 2 — Executor core + state machine + `input` handler
**Build:** `executor.py`: `step(run_id, store)` readiness loop + `reconcile_run_status`;
state-machine transition guard. Plus the real `input` handler (trivial: seeds shared state).
**How:** loop = find ready (`deps all in done|skipped`) → run handler → persist → reload →
repeat until none ready. Test the loop against a real chain of `input` nodes.
**Test:** `test_executor.py` — a multi-node `input` chain reaches `completed`; a node with an
unmet dep never runs; reconcile sets the right terminal run status.

### Phase 3 — Deterministic handlers: branch, tool, approval
**Build:** `handlers.py` + `registry.py`: `branch` (skip losing paths), `tool` (idempotent
mock Linear/invoice), `approval` (parks `awaiting_approval`).
**How:** per LLD §5–§8. Idempotency guard on `tool` (`run_id:node_key`, persist before return).
**Test:** `test_handlers.py` — branch marks 2 paths `skipped` and `final` still becomes ready;
tool retried twice → one side-effect, identical output; approval handler parks the node.

### Phase 4 — Agent node (Groq)
**Build:** `schemas.py` `Classification` model; `agent/classify.py`: Groq call
(Llama 3.3 70B) → raw → `Classification.model_validate_json`; the `agent` handler.
**How:** `groq` client, structured prompt forcing JSON `{label, reply}`; Pydantic validates
**before** return — invalid output raises → node `failed`. `GROQ_API_KEY` from env.
**Test:** real Groq on "I was double-charged" → `{label: "billing"}`, agent `done`;
the `Classification` validator fed a malformed payload (real validator, real call) raises →
agent maps to `failed`, downstream blocked.

### Phase 5 — API layer
**Build:** `routers/runs.py`: `POST /runs/execute/{graph_id}`, `GET /runs/{id}`,
`POST /nodes/{id}/retry`, `POST /nodes/{id}/approve`, `POST /nodes/{id}/reject`.
**How:** each mutating endpoint mutates one node then `await step()`; returns refreshed run +
nodes + logs (per flow.md).
**Test:** httpx client — execute a graph → returns run state; retry endpoint asserts
`failed` precondition; approve resumes a parked run.

### Phase 6 — Frontend debugger
**Build:** one page: submit form → run view (node status badges) → node panel
(input/output/error/logs) → Retry / Approve / Reject buttons. Poll `GET /runs/{id}`.
**How:** existing Next.js kit + `use-api` hook; no graph canvas.
**Test:** manual — submit each of the 3 request types, watch statuses, retry a failure,
approve a pause.

### Phase 7 — Final: integration + the DAG engine
**Build:** wire `seeds/support_graph.json` — the assignment workflow, **8 nodes**:
`input → {classify, fetch_context} → branch → {bug, billing, approval} → final`.
`classify` (agent) and `fetch_context` (tool, mock customer/account lookup = task.pdf step 3)
run in parallel off `input` and both feed `branch`. Seed one `graphs` + `graph_versions` row
on startup, connect Groq agent + all handlers + API into the running engine.
README + design writeup (HLD §2).

Node/edge contract:
| node | type | deps | condition |
|------|------|------|-----------|
| input | input | — | — |
| classify | agent | input | — |
| fetch_context | tool | input | — |
| branch | branch | classify, fetch_context | — |
| bug | tool | branch | label == bug |
| billing | tool | branch | label == billing |
| approval | approval | branch | label == unclear |
| final | tool | bug, billing, approval | — |
**How:** end-to-end assembly; the seed graph is the assignment workflow.
**Test:** `test_scenarios.py` — **the 5 acceptance scenarios, all green:**
1. **Branching** — billing request → only billing path runs, others `skipped`, run `completed`.
2. **Retry** — force a tool failure → `/retry` → run completes.
3. **Approval** — unclear request → `awaiting_approval` → `/approve` → `completed`.
4. **Validation-failure** — agent returns invalid output → agent `failed`, downstream blocked.
5. **Idempotency** — retry a completed tool node → one side-effect, identical output.

This phase ending green = the DAG engine is done and the assignment is met.

---

## Success Criteria

- [ ] `alembic upgrade head` clean; 5 tables present.
- [ ] `step()` executes nodes only after deps `done|skipped`; terminates naturally.
- [ ] Conditional branch routes correctly; losing paths `skipped`; `final` still fires.
- [ ] Agent output Pydantic-validated before downstream; invalid → node `failed`, no cascade.
- [ ] Failed node retried via API → reruns and completes.
- [ ] Tool retry → exactly one side-effect (idempotency key `run_id:node_key`).
- [ ] Every node persists input, output, error, status + ordered logs.
- [ ] Groq agent node classifies real requests into bug/billing/unclear.
- [ ] Debugger UI: submit, see statuses, inspect node I/O/logs, retry, approve.
- [ ] `test_scenarios.py` — all 5 green.

## Open Questions

- Agent scenario tests require `GROQ_API_KEY` and a live call. Run them as part of the suite
  (assumed) — they fail loudly if the key is missing or the model misbehaves, which is correct.
- Reject semantics: `/reject` sets approval `failed` and run `failed` with logged reason
  (assumed) — no alternate routing.
