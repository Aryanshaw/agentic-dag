# Architecture

Read this first if you're new. It explains **what the system does** and **how the
pieces fit**, in plain terms. Deep details live in `docs/HLD.md` and `docs/LLD.md`.

---

## 1. What is this thing?

A **workflow engine**. You give it a customer-support message like
*"I was double-charged on my invoice"*. It runs that message through a series of
steps — classify it, look up the customer, decide where to route it, take an
action, sometimes pause for a human — and produces a reply.

Those steps are wired together as a **graph** (a flowchart). Each box is a
**node**; each arrow is an **edge**. The engine walks the graph, running each node
when its turn comes.

```
input → classify ─┐
      → fetch_context ─┴→ branch → { bug | billing | approval } → final
```

Every node's status, input, output, and logs are saved to a database, so you can
inspect exactly what happened — that's why the UI is called a **debugger**.

---

## 2. The vocabulary (learn these 5 words)

| Word | Meaning |
|------|---------|
| **Graph** | The flowchart definition: a list of nodes + a list of edges. Stored as JSON. |
| **Node** | One step. Has a `type` that decides what it does. |
| **Edge** | An arrow `A → B`. Means "B runs after A" **and** "B receives some of A's output". |
| **Run** | One execution of a graph for one request. Has many node-runs. |
| **step()** | The function that actually walks the graph and runs nodes. |

---

## 3. The 5 node types

Each node has a `type`. The `type` picks a **handler** — a small function that
knows how to run that kind of node. That's the whole extensibility story: new
behaviour = new type + new handler.

| Type | What it does |
|------|--------------|
| `input` | Entry point. Seeds the graph with the request. (Also used as a pass-through.) |
| `agent` | Calls the **LLM (Groq)**, then validates the JSON it returns. Used to classify, and to write the final reply. |
| `branch` | Looks at the classification and **kills the paths not taken** (marks them `skipped`). |
| `tool` | Performs a side-effect (create a ticket, check an invoice). **Idempotent.** |
| `approval` | **Pauses** the run and waits for a human to click Approve/Reject. |

---

## 4. How a node moves through life (the state machine)

Every node-run has a `status`. It can only change along these arrows:

```
pending ──▶ running ──▶ done
                    ├──▶ failed ──▶ pending      (Retry re-runs it)
                    └──▶ awaiting_approval ──▶ done    (Approve)
                                          └──▶ failed  (Reject)
pending ──▶ skipped     (a branch decided this path isn't taken)
```

These transitions are **enforced** in one place (`store.set_status`). If code tries
an illegal jump (e.g. `done → running`), it's rejected. This is what makes retries
safe: you can never accidentally re-run a node that already finished.

**Key idea:** `done` and `skipped` both count as "resolved". A node is ready to run
when *all* its upstream nodes are resolved. So when `branch` skips the losing paths,
the join node `final` still becomes ready off the one live path.

---

## 5. The engine loop — `step()`

`step()` is the heart. It's a simple loop (see `engine/executor.py`):

```
load the edges
loop:
    load all nodes fresh from the DB
    find "ready" nodes = pending AND all their deps are resolved
    if none ready: stop
    for each ready node:
        build its input from upstream outputs
        mark running → call the handler → save output → mark done
        (if the handler threw: mark failed)
reconcile the run's overall status
```

Two properties matter, and they come straight from this design:

1. **Stateless / re-entrant.** `step()` keeps nothing in memory between calls. It
   re-reads everything from the DB every time. So calling it once, or calling it
   again after a retry, behaves identically.

2. **Retry = resume = re-run the loop.** There's no separate "resume" code. To
   retry a failed node you set it back to `pending` and call `step()` again — the
   loop picks up where it left off. To resume after approval you set the approval
   node to `done` and call `step()`. Same function every time.

There is **no background worker or queue.** `step()` runs *inline* during the API
request. A run "pauses" simply because no one is calling `step()` right now — it's
sitting in the DB waiting for the next Approve/Retry click.

---

## 6. How data flows between nodes

An edge carries data, not just order. Each edge says:

```json
{ "source": "classify", "target": "final",
  "sourceHandle": "label", "targetHandle": "label" }
```

Read as: *"take the `label` field from classify's output, and put it into final's
input under the key `label`."* Before a node runs, `build_input` walks all edges
pointing at it and assembles its input dict this way. Skipped upstream nodes
contribute `null`.

**Dependencies are derived from edges, never stored.** "What does node X depend on?"
is answered by scanning the edge list (`deps_of`). Nothing to keep in sync, nothing
to corrupt.

---

## 7. The three tricky behaviours (and how they're handled)

### Branching
`branch` reads the LLM's `label` (bug / billing / unclear). For every outgoing edge
whose `condition` doesn't match the label, it marks that target `skipped`. The
winning path stays `pending` and runs; the others are resolved-as-skipped. No nodes
are deleted, so the run is fully recoverable and inspectable.

### Approval (human in the loop)
The `approval` handler sets the node to `awaiting_approval` and returns. `step()`
sees nothing else is ready and stops. The run just... waits. When a human clicks
**Approve**, the API sets the node to `done` and calls `step()` again — now `final`
becomes ready and the run finishes. **Nothing re-runs from the start**; the already-
`done` nodes stay done (the state machine forbids re-running them).

### Idempotency (do the side-effect exactly once)
`tool` nodes create real-ish effects (a Linear ticket). We must never create two
tickets if a node is retried. Two guards:

1. Before acting, the handler checks: does this node already have saved output?
   If yes, replay it — don't act again.
2. The mock tool itself dedupes on an **idempotency key** (`run_id:node_key`). Even
   if the process crashed *after* the side-effect but *before* saving output, the
   retry finds the key and returns the same result instead of firing twice.

Output is always **persisted before the handler returns** — that ordering is what
makes guard #2 possible.

---

## 8. The agent (LLM) node

`agent` nodes call Groq (Llama 3.3 70B). The important rule: **validate the LLM's
output before anyone downstream uses it.**

- `classify` asks the LLM for `{label, reply}`. If the LLM returns something that
  doesn't match the schema (e.g. a label outside the allowed set), Pydantic raises,
  the node goes `failed`, and downstream nodes stay blocked. Bad data never spreads.
- `final` is also an agent. It receives the whole run context (the label, the
  account, the winning branch's result) and asks the LLM to **write the customer
  reply**. This is why the reply is natural text, not a hardcoded string.

The schema each agent validates against is **data, not code**: it's declared in the
node's `config.output_schema` as JSON, and a Pydantic validator is built from it at
runtime (`engine/schemas.py`). So you can change a node's expected output by editing
the graph JSON — no Python changes.

---

## 9. Where everything lives

```
api/
  models.py          5 DB tables (see below)
  engine/
    graph.py         pure functions: deps_of, is_dag (cycle check), build_input
    store.py         the ONLY place that touches SQL
    registry.py      type → handler map
    handlers.py      the 5 handlers (input, agent, branch, tool, approval)
    schemas.py       builds a Pydantic validator from JSON (schema-as-data)
    mocks.py         fake Linear/invoice tools, idempotent
    executor.py      step() loop + reconcile_run_status
    seed.py          loads the support graph on startup
  agent/classify.py  the Groq call
  seeds/support_graph.json   the actual workflow definition
  routers/runs.py    the HTTP endpoints
client/
  src/app/page.tsx   the debugger UI (graph canvas + node inspector)
  src/lib/api.ts     typed fetch helpers
```

**One rule worth repeating:** all SQL lives in `store.py`. The engine and handlers
stay pure-ish — they take input, return output, and go through `store` for anything
persistent. That's why they're easy to test.

---

## 10. The database (5 tables)

```
graphs ──< graph_versions ──< runs ──< node_runs ──< node_logs
```

| Table | Holds |
|-------|-------|
| `graphs` | A named workflow (e.g. "Customer Support Triage"). |
| `graph_versions` | A frozen `{nodes, edges}` JSON definition. A run pins one version. |
| `runs` | One execution: its request + overall status. |
| `node_runs` | Per-node state: status, input, output, error, attempts, idempotency key. |
| `node_logs` | Timeline of log lines per node (what the debugger shows). |

Definition (`graphs`/`graph_versions`) is separate from execution (`runs` and
below). Editing a graph can never corrupt an in-flight run, because the run pinned
its own version.

---

## 11. The request lifecycle (end to end)

1. UI loads the graph definition (`GET /graphs/{id}`) and draws the skeleton.
2. You type a message, hit **Run** → `POST /runs/execute/{graph_id}`.
3. The API creates a `run` + one `node_run` per node, then calls `step()`.
4. `step()` walks the graph: `input` → `classify`+`fetch_context` (parallel) →
   `branch` (skips losers) → the one live action → `final` (LLM writes reply).
5. If it hits `approval`, `step()` stops and the run sits at `awaiting_approval`.
6. The API returns the full run (nodes + statuses + logs + edges). The UI renders
   it and animates the traversal.
7. **Approve / Retry / Reject** each mutate one node and call `step()` again — the
   same loop resumes the same run.

That's the whole system. Everything else is detail.
