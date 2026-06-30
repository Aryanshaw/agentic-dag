# Code Flow — Agentic DAG Engine

## When you hit `POST /runs/execute/{graph_id}`

```mermaid
sequenceDiagram
    actor User
    participant API as API (FastAPI)
    participant Store
    participant Exec as Executor.step()
    participant DB

    User->>API: "POST /runs/execute/{graph_id} { request }"
    API->>Store: load pinned graph_version.definition
    Store->>DB: SELECT graph_versions
    API->>Store: "create run (status=running)"
    API->>Store: "create one node_run per node (status=pending)"
    Store->>DB: INSERT run + node_runs
    API->>Exec: "step(run_id)"
    Exec-->>API: "run state (running / awaiting_approval / completed / failed)"
    API-->>User: "200 { run, nodes, logs }"
```

## When `step()` runs (the engine loop)

```mermaid
flowchart TD
    A[step run_id] --> B[load node_runs from DB]
    B --> C{any pending node<br/>whose deps all<br/>done or skipped?}
    C -- no --> Z[reconcile run status:<br/>running / awaiting_approval / completed / failed]
    C -- yes --> D[pick ready node]
    D --> E[build_input from incoming edges]
    E --> F[set status = running, log start]
    F --> G[REGISTRY type → handler input]
    G --> H{handler outcome}
    H -- returned output --> I[set_output, status = done]
    H -- parked itself --> J[status = awaiting_approval]
    H -- marked a path --> K[targets set = skipped]
    H -- raised --> L[status = failed, log error]
    I --> B
    J --> B
    K --> B
    L --> B
    Z --> Y[return run state]
```

## When a request takes the branch + tool path

```mermaid
sequenceDiagram
    actor User
    participant API
    participant Exec as step()
    participant Agent as agent handler
    participant LLM
    participant Tool as tool handler

    User->>API: "POST /execute { 'billing question...' }"
    API->>Exec: "step(run)"
    Exec->>Exec: input → done
    par classify ∥ fetch_context (parallel off input)
        Exec->>Agent: run classify
        Agent->>LLM: "classify(text)"
        LLM-->>Agent: raw output
        Agent->>Agent: "Pydantic validate → {label: 'billing'}"
        Agent-->>Exec: done
    and
        Exec->>Exec: "fetch_context → mock account lookup → done"
    end
    Exec->>Exec: branch (waits for both) → mark bug & approval = skipped
    Exec->>Tool: "billing → mock invoice (idempotent) + draft reply"
    Tool-->>Exec: done
    Exec->>Exec: final → done
    Exec-->>API: completed
    API-->>User: "200 { run: completed }"
```

## When a request hits the human-approval path (pause + resume)

```mermaid
sequenceDiagram
    actor User
    participant API
    participant Exec as step()

    User->>API: "POST /execute { 'vague request...' }"
    API->>Exec: "step(run)"
    Exec->>Exec: "input → (classify{label:'unclear'} ∥ fetch_context) → branch"
    Note over Exec: bug & billing set skipped
    Exec->>Exec: "approval node → status = awaiting_approval"
    Note over Exec: no ready nodes → loop halts
    Exec-->>API: awaiting_approval
    API-->>User: "200 { run: awaiting_approval }"

    User->>API: "POST /nodes/{approval_id}/approve"
    API->>Exec: "set approval = done; step(run)"
    Exec->>Exec: final → done
    Exec-->>API: completed
    API-->>User: "200 { run: completed }"
```

## When you retry a failed node

```mermaid
sequenceDiagram
    actor User
    participant API
    participant Exec as step()

    User->>API: "POST /nodes/{id}/retry"
    API->>API: assert node.status == failed
    API->>API: set status = pending, attempts++
    API->>Exec: "step(run)"
    Note over Exec: node pending again → becomes ready → reruns
    Exec-->>API: refreshed run state
    API-->>User: "200 { run, nodes }"
```

## When a tool node is retried (idempotency)

```mermaid
flowchart TD
    A[tool handler runs] --> B{output_json<br/>already set?}
    B -- yes --> C[log idempotent hit<br/>return cached output<br/>NO side-effect]
    B -- no --> D[run mock side-effect<br/>idem_key = run_id:node_key]
    D --> E[persist output_json BEFORE return]
    E --> F[return output]
```
