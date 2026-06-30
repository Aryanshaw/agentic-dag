# Low-Level Design — Agentic DAG Engine

> Companion to [HLD.md](./HLD.md). HLD = boxes/arrows/why. This = schemas,
> state machine, algorithms, contracts. Assignment scope only.

---

## 1. Persistence schema

Core distinction: **definition vs instance.** A *graph* is a reusable template drawn
once; a *run* is one execution of it. Deps are **not** stored anywhere — derived from `edges`.

```
graphs ──< graph_versions ──< runs ──< node_runs ──< node_logs
                 │                          
       run pins to ONE version → editing a board never corrupts in-flight runs
```

### `graphs`  (the board's identity)
| column | type | note |
|--------|------|------|
| id | uuid PK | |
| name | text | board name |
| latest_version | int | convenience pointer |
| created_at / updated_at | timestamptz | |

### `graph_versions`  (immutable snapshots — the versioning answer to "edit edges mid-run")
| column | type | note |
|--------|------|------|
| id | uuid PK | |
| graph_id | uuid FK | |
| version | int | 1, 2, 3… monotonic |
| definition | json | `{nodes:[{key,type,config}], edges:[{source,target,sourceHandle,targetHandle,condition?}]}` |
| created_at | timestamptz | snapshots are never mutated; an edit = a new row |

Editing a board writes a **new version**. Runs pin to the version they started on, so
edits never corrupt running executions (this is the n8n / Temporal model). For the
assignment, seed one `graphs` + one `graph_versions` row for the support flow.

### `runs`
| column | type | note |
|--------|------|------|
| id | uuid PK | |
| graph_version_id | uuid FK | the pinned definition this run executes |
| status | text | `running` · `awaiting_approval` · `completed` · `failed` |
| request | json | the original input payload |
| created_at / updated_at | timestamptz | |

### `node_runs`  (one row per node *per run* — a run's working state)
| column | type | note |
|--------|------|------|
| id | uuid PK | |
| run_id | uuid FK | |
| node_key | text | stable id within the graph, e.g. `classify` |
| type | text | `input`·`agent`·`branch`·`tool`·`approval` |
| status | text | see §2 state machine |
| config | json | static node settings (prompt, branch rules, tool name) |
| input_json | json | resolved input at execution time |
| output_json | json | result (also serves as the idempotency cache) |
| error | text | last error message |
| attempts | int | retry counter |
| idempotency_key | text | `"{run_id}:{node_key}"`, set before side-effect |
| created_at / updated_at | timestamptz | |

### `node_logs`  (the trace)
| column | type | note |
|--------|------|------|
| id | uuid PK | |
| node_run_id | uuid FK | |
| ts | timestamptz | |
| level | text | `info`·`error` |
| message | text | |
| data | json | optional structured payload |

### Instantiation
On `POST /runs`, the engine reads the pinned `graph_versions.definition`, creates one
`node_runs` row per node (all `pending`), then calls `step()`. The definition's `edges`
stay in the version JSON — never copied into `node_runs`, since deps are derived (§3).

## 2. Node state machine

```
                ┌──────────── retry ───────────┐
                ▼                               │
   pending ──► running ──► done                 │
      │           │                             │
      │           ├──► failed ───────────────────┘
      │           │
      │           └──► awaiting_approval ──(approve)──► done
      │                                   └─(reject)──► failed
      └──► skipped         (branch marked this path dead)
```

Allowed transitions (enforce in `set_status`):

| from | to | trigger |
|------|----|---------|
| pending | running | executor picks it (deps resolved) |
| running | done | handler returned valid output |
| running | failed | handler raised / validation failed |
| running | awaiting_approval | approval node reached |
| failed | pending | retry endpoint |
| awaiting_approval | done | approve endpoint |
| awaiting_approval | failed | reject endpoint |
| pending | skipped | branch node killed this path |

`done` and `skipped` are both **terminal-resolved** — readiness treats them identically.

## 3. Dependencies, derived from edges

```python
def deps_of(node_key, edges):
    return [e["source"] for e in edges if e["target"] == node_key]

def is_dag(nodes, edges) -> bool:
    # Kahn's algorithm: peel nodes with in-degree 0; if any remain, there's a cycle
    indeg = {n["key"]: 0 for n in nodes}
    for e in edges: indeg[e["target"]] += 1
    queue = [k for k, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        k = queue.pop(); seen += 1
        for e in (x for x in edges if x["source"] == k):
            indeg[e["target"]] -= 1
            if indeg[e["target"]] == 0: queue.append(e["target"])
    return seen == len(nodes)   # False ⇒ cycle ⇒ reject graph
```

Validate `is_dag` once when a graph is loaded/saved, not on every run.

## 4. The executor — `step()`

The heart. Stateless, re-entrant. Called by submit/retry/approve.

```python
async def step(run_id, store):
    nodes = await store.get_nodes(run_id)        # current persisted state
    edges = graph_of(run_id).edges
    while True:
        ready = [n for n in nodes
                 if n.status == "pending"
                 and all(dep.status in ("done", "skipped")
                         for dep in (nodes[k] for k in deps_of(n.node_key, edges)))]
        if not ready:
            break                                # blocked, awaiting approval, or complete
        for n in ready:
            inp = build_input(n.node_key, edges, nodes)
            await store.set_status(n.id, "running")
            await store.append_log(n.id, "info", "start", inp)
            try:
                handler = REGISTRY[n.type]
                out = await handler(n, inp, store)        # may set awaiting_approval / skipped
                if n.status == "running":                 # handler didn't park it
                    await store.set_output(n.id, out)
                    await store.set_status(n.id, "done")
            except Exception as e:
                await store.set_status(n.id, "failed")
                await store.append_log(n.id, "error", str(e))
        nodes = await store.get_nodes(run_id)    # reload; statuses changed
    await reconcile_run_status(run_id, store)    # running / awaiting_approval / completed / failed
```

```python
def build_input(node_key, edges, nodes):
    inp = {}
    for e in edges:
        if e["target"] == node_key:
            up = nodes[e["source"]]
            inp[e["targetHandle"]] = (up.output_json or {}).get(e["sourceHandle"])
    return inp
```

**Trigger model (pinned):** there is **no background daemon**. `step()` runs only when an
endpoint calls it — `POST /runs`, `/retry`, `/approve` each run it until it blocks. That
*is* the re-entrant stepper. A run "pauses" simply because no endpoint is calling `step()`.

## 5. Node types & contracts

### Taxonomy (generic — the categories every engine has)

| category | role | examples | build now? |
|----------|------|----------|-----------|
| **trigger / input** | entry point, source of data | manual, webhook, schedule, form | ✅ `input` |
| **agent / LLM** | model call → output or decision | classify, draft, summarize | ✅ `agent` |
| **branch / router** | route on data | if, switch | ✅ `branch` |
| **tool / action** | side-effecting external call | API, DB write, mock Linear/invoice | ✅ `tool` |
| **wait / human** | suspend until an external signal | approval, wait-for-webhook, timer | ✅ `approval` |
| **transform / code** | pure data mapping, no side-effect | map/format fields | later — one handler, no engine change |
| **output / sink** | terminal result | final response | later (or reuse `tool`) |

> **HITL is not special** — `approval` is the human case of a general **wait/suspend**
> node: it parks in `awaiting_signal`, the executor halts, an external event (human
> approve / webhook / timer) flips it to `done` and re-triggers `step()`. Same resume
> path as retry. Build `approval` as its own type now; it generalizes to `wait` later.

Adding any new type = registering one handler in `REGISTRY`. The executor never changes.

### Handler contracts (the 5 built now)

Each handler: `async (node, input, store) -> output_dict`.

| type | input | output | behavior |
|------|-------|--------|----------|
| **input** | the run's `request` | `{request: ...}` | seeds shared state; always `done` |
| **agent** | upstream text | `{label, reply?}` | calls the LLM; **Pydantic-validates** before returning (see §6) |
| **branch** | `{label}` | `{label}` | reads label; for each outgoing edge whose `condition` ≠ label, set that target `skipped` (§8) |
| **tool** | branch context | `{ticket_id}` / `{invoice}` | **idempotent** mock side-effect (§7) |
| **approval** | draft reply | — | sets own status `awaiting_approval`, returns nothing; executor halts |

## 6. Validation-failure path (pinned · scenario)

```python
class Classification(BaseModel):
    label: Literal["bug", "billing", "unclear"]
    reply: str | None = None

async def agent_handler(node, inp, store):
    raw = await claude_classify(inp["text"], node.config["prompt"])
    try:
        result = Classification.model_validate_json(raw)   # strict parse
    except ValidationError as e:
        await store.append_log(node.id, "error", f"invalid agent output: {e}")
        raise                                              # → node = failed
    return result.model_dump()
```

On validation failure: node → `failed`, error in `node_logs`, **downstream stays blocked**
(its deps are unmet, so it never becomes ready). Retry re-runs the agent node only.

## 7. Idempotency mechanics (pinned · scenario)

```python
async def tool_handler(node, inp, store):
    if node.output_json is not None:          # already executed this run → replay cached result
        await store.append_log(node.id, "info", "idempotent hit; skipping side-effect")
        return node.output_json
    key = f"{node.run_id}:{node.node_key}"    # stable across retries
    result = mock_create_linear_issue(inp, idem_key=key)   # mock keys on this too
    await store.set_output(node.id, result)   # persist BEFORE returning
    return result
```

- Key format: `run_id:node_key` — stable across any number of retries.
- Check-before-side-effect: if `output_json` exists, return it, don't re-run the effect.
- Storage: result lives in `node.output_json` (doubles as the cache).
- **Partial-failure case:** if the process dies *after* the side-effect but *before*
  `set_output`, a retry would re-run it. Mitigation for mocks: the mock itself dedupes on
  `idem_key`. (Real systems need a `side_effects` write-ahead row; out of scope, noted.)

## 8. Branch-skip mechanics (pinned · scenario)

```python
async def branch_handler(node, inp, store):
    label = inp["label"]
    for e in outgoing_edges(node.node_key):
        if e.get("condition") and e["condition"] != label:
            target = await store.get_node(node.run_id, e["target"])
            await store.set_status(target.id, "skipped")     # dead path
    return {"label": label}
```

Readiness rule (§4) counts `skipped` as resolved, so `final` (which depends on all three
branch outputs) still fires off the one live path. No node deletion, fully recoverable.

## 9. API surface

| method | path | body | effect |
|--------|------|------|--------|
| POST | `/runs` | `{graph_id, request}` | create run + seed nodes; `step()`; return run |
| GET | `/runs/{id}` | — | run + all nodes (status/input/output/error) + logs |
| POST | `/nodes/{id}/retry` | — | `failed → pending`; `attempts++`; `step()` |
| POST | `/nodes/{id}/approve` | — | `awaiting_approval → done`; `step()` |
| POST | `/nodes/{id}/reject` | `{reason?}` | `awaiting_approval → failed`; log reason |

All mutating endpoints end by calling `step()` and returning the refreshed run — that's the
re-entrant model surfaced to the client.

## 10. Frontend (debugger, minimal)

One page: submit form → run view. Run view lists nodes with status badges; click a node →
panel showing `input_json` / `output_json` / `error` / logs. Buttons: **Retry** (on failed),
**Approve / Reject** (on awaiting_approval). Poll `GET /runs/{id}` every ~1s. No graph canvas
needed for the assignment.

## 11. Scenario → design map  (submission checklist)

| Required scenario | Covered by | Test asserts |
|-------------------|------------|--------------|
| **Branching** | §8 branch-skip; readiness counts `skipped` | bug request → only `bug` path runs, `billing`/`approval` `skipped`, `final` done |
| **Retry** | §2 `failed→pending`; §4 re-entrant `step()` | force a node failure → retry → it reruns, run completes |
| **Approval** | §5 approval handler parks; §9 `/approve` | unclear request halts at `awaiting_approval`; approve → resumes to `final` |
| **Validation failure** | §6 Pydantic strict parse | bad LLM output → agent `failed`, downstream blocked, error logged |
| **Idempotency** | §7 check-before-side-effect | run tool node, retry it → exactly one side-effect, same `output_json` |

## 12. Build order

1. Models + migration (`runs`, `nodes`, `node_logs`).
2. Store interface + SQLAlchemy impl.
3. Graph helpers: `deps_of`, `is_dag`, `build_input`.
4. Node registry + 5 handlers (agent uses a rule-based classifier first, Claude after).
5. `step()` executor + `reconcile_run_status`.
6. Seed graph JSON for the support flow.
7. API endpoints.
8. 5 scenario tests (§11) — these are the acceptance gate.
9. Next.js debugger.
10. README + wire HLD §2 decision table in as the design writeup.
