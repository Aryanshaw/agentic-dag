# Agentic DAG Workflow Engine

A backend workflow engine that executes a **DAG of typed nodes** with agent-style
decision making. A run classifies a customer-support request with an LLM, branches on the
decision, calls idempotent mock tools, pauses for human approval, persists every node's
state + trace, retries failed nodes, and resumes — all driven by a stateless re-entrant
stepper. A thin Next.js page acts as a workflow debugger.

- **api/** — FastAPI + SQLAlchemy 2.0 async + SQLite + Alembic; Groq (Llama 3.3 70B) agent.
- **client/** — Next.js debugger (submit · statuses · inspect I/O/logs · retry · approve).
- **docs/** — [SPEC](docs/SPEC.md) (build contract), [HLD](docs/HLD.md) (design + decisions),
  [LLD](docs/LLD.md) (schema/state-machine/algorithms), [flow](docs/flow.md), [plans/](docs/plans).

## Prerequisites
- Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/), Node ≥ 18.

## Setup
```bash
uv sync --directory api      # Python deps
pnpm install                 # frontend deps
```

### Environment (`api/.env`)
```
DATABASE_URL=sqlite+aiosqlite:///./local.db
GROQ_API_KEY=gsk_...         # required: the agent makes real Groq calls
```

### Database
```bash
uv --directory api run alembic upgrade head
```
The support-triage graph is **seeded automatically on API startup** (idempotent).

## Running
```bash
pnpm dev          # API :8000 + client :3000
pnpm dev:api      # API only  → http://localhost:8000
pnpm dev:client   # client only → http://localhost:3000
```
Open the client, type a support request, hit **Run workflow**, watch node statuses, click a
node to inspect input/output/logs, and use Retry / Approve / Reject.

## Tests
```bash
uv --directory api run pytest -q                          # full suite
uv --directory api run pytest tests/test_scenarios.py -q  # the 5 acceptance scenarios
```
The agent scenarios make **real Groq calls** (no stubs) with unambiguous inputs, so they
need `GROQ_API_KEY`. The 5 scenarios cover **branching, retry, approval, validation-failure,
idempotency**.

## Design explanation (short)

The full rationale is the decision table in [HLD §2](docs/HLD.md); the load-bearing choices:

| Decision | Why |
|----------|-----|
| **Custom engine, not a framework** | The exercise grades engine design; a framework would hide it. |
| **State lives in the DB; engine is a stateless re-entrant stepper** | Retry and resume become the *same* operation — re-run the loop over persisted state. Survives restarts. |
| **Deps derived from edges, never stored** | Editing the graph can't corrupt a run; there's nothing stale to corrupt. |
| **Branch = mark losing path `skipped`** | Readiness treats `skipped` like `done`, so the join node still fires. No runtime node deletion. |
| **Idempotency key `run_id:node_key` on tool nodes** | A retry replays the cached output; the mock also dedupes on the key, so a crash mid-side-effect still yields exactly one effect. |
| **Agent output is schema-as-data** | The node carries its output schema as JSON; a Pydantic validator is built at runtime and validates **before** any downstream node runs. Invalid → node `failed`, downstream blocked. |
| **No queue/worker/daemon** | `step()` runs inline per request (submit/retry/approve). A run "pauses" simply because no endpoint is calling `step()`. |

### How a run flows
`input → classify (LLM, validated) → branch → {bug | billing | approval} → final`.
The executor runs every node whose deps are all `done|skipped`, persists each result,
and stops when blocked (awaiting approval), failed, or complete. Node lifecycle:
`pending → running → done | failed | skipped | awaiting_approval`, with `failed→pending`
(retry) and `awaiting_approval→done|failed` (approve/reject) as the resume edges.

## Layout
```
api/
  models.py            5 tables: graphs · graph_versions · runs · node_runs · node_logs
  engine/
    graph.py           deps_of · is_dag (Kahn) · build_input        (pure)
    store.py           persistence — the only SQL touchpoint
    registry.py        type → handler map
    handlers.py        input · agent · branch · tool · approval
    schemas.py         schema-as-data validator (build_model)
    mocks.py           idempotent mock Linear/invoice (fault knobs for scenarios)
    executor.py        step() loop + reconcile_run_status
    seed.py            seeds the support graph on startup
  agent/classify.py    Groq call (Llama 3.3 70B)
  seeds/support_graph.json
  routers/runs.py      execute · get · retry · approve · reject · graphs
  tests/               graph · executor · handlers · agent · api · scenarios
client/src/
  lib/api.ts           typed fetch helpers
  app/page.tsx         the debugger page
```
