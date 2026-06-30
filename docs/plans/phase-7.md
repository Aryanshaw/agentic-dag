# Phase 7 Plan — Integration + 5 scenario tests (acceptance gate)

## Files
- `api/seeds/support_graph.json` — the assignment workflow `{nodes, edges}`:
  - nodes: input, classify(agent, output_schema=classification), branch, bug(tool linear), billing(tool invoice), approval, final(input).
  - edges: input→classify(text), classify→branch(label), branch→{bug|billing|approval}(condition), input→bug(text)/input→billing(text) pass-through (so tools get request text), {bug,billing,approval}→final(reply).
- `api/engine/seed.py` — `load_support_def()`; `seed_support_graph(db)`: validate `is_dag`, insert one graph+version if absent. Called from `main.lifespan`.
- `api/routers/runs.py` — add `GET /graphs` (id, name, latest_version) so the UI can pick the seeded graph.
- `api/main.py` — call `seed_support_graph` on startup.
- `api/tests/test_scenarios.py` — 5 scenarios through the API (override get_store + temp db; seed graphs in-test).

## Scenario design (real code paths, no stubs)
1. **Branching** — full support graph, "double-charged" request → real Groq → billing; bug & approval `skipped`, run `completed`.
2. **Retry** — minimal graph input→tool(`fail_until:1`)→final: execute → tool `failed`, run `failed`; `/retry` → `completed`; created_count==1.
3. **Approval** — full support graph, vague request → real Groq → unclear → `awaiting_approval`; `/approve` → `completed`.
4. **Validation-failure** — support graph, classify config prompt forces out-of-enum label → real Groq → agent `failed`, branch/downstream blocked, run `failed`.
5. **Idempotency** — minimal graph input→tool(`crash_after_create:true`)→final: execute → side-effect fires, then crash → `failed`; `/retry` → mock dedupes on idem_key → `completed`, created_count==1, identical output.

## Gate
`pytest tests/test_scenarios.py` all 5 green; `alembic upgrade head` clean; startup seeds the graph.
