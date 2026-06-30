# High-Level Design — Agentic DAG Engine

> Scope note: this document describes a **generic DAG workflow engine**. The
> take-home assignment is one *seed graph* run on that engine. Everything under

---

## 1. Problem & goal

Build a workflow engine that executes a **DAG** of nodes where:

- steps are fixed and inspectable (you can see every node's input/output/logs),
- selected nodes make **dynamic decisions** (an LLM classifies, then the graph branches),
- the system is **reliable**: failed nodes retry/resume, tool side-effects are idempotent,
- the whole run is **debuggable**: persisted state + per-node traces.

The reference workflow: customer-support triage → classify → branch (bug / billing /
unclear) → draft reply → final response, with a human-approval pause on the unclear path.

## 2. Guiding decisions (the "design explanation")

These are the load-bearing choices. Each one is deliberate; the rationale here doubles
as the submission's required design writeup.

| # | Decision | Why | Rejected alternative |
|---|----------|-----|----------------------|
| D1 | **Custom engine, not a framework** | The exercise grades *engine design*. A framework (LangGraph/Temporal/Prefect) would hide the exact thing being evaluated. | LangGraph (too much agent magic), Temporal/Prefect/Celery (distributed infra, weeks of overkill) |
| D2 | **State lives in the DB; the engine is a stateless re-entrant stepper** | Makes retry and resume the *same* operation — re-run the loop over persisted state. Survives crashes. | In-memory run state (lost on restart, can't resume) |
| D3 | **Edges are the single source of truth for dependencies** | Deps are *derived* from edges, never stored. Editing edges can't corrupt the graph because there's nothing stale to corrupt. | A stored `deps[]` field per node (goes stale when edges change) |
| D4 | **Idempotency keys on tool nodes** | Retry must not duplicate side-effects (no double Linear issue). Key = `run_id:node_id`. | Best-effort retry (duplicates side effects) |
| D5 | **Branch = mark losing path `skipped`** | Conditional routing needs no new machinery; readiness treats `skipped` like `done`, so downstream still fires. | Deleting nodes at runtime (mutates the graph, unrecoverable) |
| D6 | **Libraries only for non-core primitives** | Pydantic (validation), Anthropic SDK (the LLM), SQLAlchemy (persistence). Write the orchestration; borrow the boring parts. | Hand-rolling validation/HTTP/ORM |

## 3. Architecture — 4 layers

```
┌─────────────────────────────────────────────────────────┐
│ L4  API / Triggers                                        │
│     POST /runs · GET /runs/{id} · POST /nodes/{id}/retry  │
│     POST /nodes/{id}/approve                               │
│     → each endpoint runs the Executor until it blocks     │
├─────────────────────────────────────────────────────────┤
│ L3  Executor (scheduler)                                  │
│     step(run): find ready nodes → run → persist → repeat  │
│     stateless · re-entrant · drives state transitions     │
├─────────────────────────────────────────────────────────┤
│ L2  State machine + Store                                 │
│     node lifecycle (pending→running→done/failed/...)      │
│     persistence behind an interface (no SQL in executor)  │
├─────────────────────────────────────────────────────────┤
│ L1  Node abstraction + registry                           │
│     Node{id,type,config}  ·  type → handler(input)->output│
│     handlers: input, agent, branch, tool, approval        │
└─────────────────────────────────────────────────────────┘
            ▲                                   │
            │ Graph{nodes, edges}  (deps derived from edges)
            ▼
        Postgres/SQLite  (runs · nodes · logs)
```

Why layers: L1+L3 are pure logic (testable in-memory, no DB). L2's persistence slides
underneath without changing the executor. The clean swap *is* the test that the layering
holds.

## 4. Component responsibilities

- **Graph** — holds `nodes` + `edges`. Validates it's a DAG (cycle check). Derives
  `deps_of(node)` from edges on demand. Builds a node's runtime input by walking incoming edges.
- **Node registry** — maps `type → handler`. A handler is `async (input, ctx) -> output`.
  Adding a node type = registering a handler. No engine changes.
- **Executor** — the readiness loop. Picks nodes whose deps are all resolved, transitions
  them through the state machine, persists each result, stops when blocked (awaiting approval),
  failed, or complete.
- **Store** — `get_run`, `get_nodes`, `set_status`, `set_output`, `append_log`. The only
  thing that touches SQL. Lets the executor stay pure.
- **Agent** — Claude call for classify + reply-draft. Output parsed/validated by Pydantic
  *before* any downstream node runs.
- **API** — thin FastAPI surface. Triggers (submit/retry/approve) all just call `step()`.

## 5. Data flow — reference run

```
submit request
  └─ create run + seed nodes (all pending)
  └─ step():
       input        → done   (request stored in shared state)
       classify     → done   (LLM → {label}; Pydantic-validated)
       branch       → done   (reads label; marks 2 of 3 paths "skipped")
       bug | billing| approval   (only the chosen one is ready)
         · bug      → mock Linear issue (idempotent) + draft reply → done
         · billing  → mock invoice check (idempotent) + draft reply → done
         · approval → status = awaiting_approval  → STEP HALTS
       final        → blocked until its one live dep is done
  └─ (if halted) POST /approve flips approval→done, calls step() again → final → done
```

Run ends when no node is `pending` and none is `ready`. Natural termination, no special end-node.

## 6. Tech stack

| Concern | Choice | Note |
|---------|--------|------|
| API | FastAPI | already scaffolded |
| Persistence | SQLAlchemy 2.0 async + SQLite (Alembic) | scaffolded; SQLite is fine for a single-process engine |
| Validation | Pydantic | the "validate agent output" requirement *is* this |
| LLM agent | Groq SDK · Llama 3.3 70B (free tier) | classify + draft; can fall back to a rule-based classifier |
| Execution | in-process, synchronous, triggered per request | no queue, no workers, no daemon |
| Frontend | Next.js debugger (existing kit) | submit · statuses · inspect · retry · approve |

## 7. Product

Listed to show the engine generalizes; each is out of assignment scope:

- **Drag-drop board builder** (n8n / Langflow style). The engine already runs arbitrary
  `{nodes, edges}` JSON — a builder is just a visual JSON editor (ReactFlow). Same execution path.
- **Custom user boards** + a board/template store.
- **Typed ports / handle type-checking** at edit time.

## 8. Future build

- **Distributed execution** — workers polling a queue, event-sourcing/replay (the Temporal
  model). Only needed when nodes must run across machines or for hours/days.

The take-home ships a **prebuilt seed board**; the product would let users build their own.
Identical engine — that's the whole point of deriving deps from edges.

## 8. Non-goals (this build)

No queue/Celery, no worker fleet, no replay engine, no auth, no horizontal scale, no
real external integrations (Linear/invoice are mocks).
