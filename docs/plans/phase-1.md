# Phase 1 Plan — Graph primitives

## Files
- `api/engine/graph.py` — pure functions over definition JSON, no DB:
  - `deps_of(node_key, edges) -> list[str]` — sources of edges targeting node_key.
  - `is_dag(nodes, edges) -> bool` — Kahn's algorithm (LLD §3).
  - `build_input(node_key, edges, nodes_by_key) -> dict` — walk incoming edges, map `sourceHandle → targetHandle` from upstream `output_json`.
  - `outgoing_edges(node_key, edges) -> list[edge]` — helper for branch handler (Phase 3).
- `api/tests/test_graph.py`.

## Notes
- `nodes` for `build_input` = dict `{node_key: NodeRun}` (executor builds this; pseudocode indexes `nodes[k]`).
- Edge shape: `{source, target, sourceHandle, targetHandle, condition?}`.
- `build_input`: `inp[targetHandle] = (up.output_json or {}).get(sourceHandle)`.

## Test (`test_graph.py`)
1. Linear graph a→b→c: `deps_of` correct; `is_dag` True.
2. Branching graph (classify→branch→{bug,billing,approval}→final): deps correct; `is_dag` True.
3. Cyclic graph a→b→a: `is_dag` False.
4. `build_input` maps sourceHandle→targetHandle from upstream output.

## Gate
`pytest tests/test_graph.py` green.
