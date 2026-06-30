"""Phase 2 gate: readiness gating + terminal reconcile on a real input chain."""

from engine.executor import step
from models import Graph, GraphVersion


async def _seed_run(db, store, nodes: list[dict], edges: list[dict], request: dict):
    """Create graph+version with this definition, a run, and one node_run per node."""
    async with db.session() as s:
        g = Graph(name="t")
        s.add(g)
        await s.flush()
        v = GraphVersion(graph_id=g.id, version=1, definition={"nodes": nodes, "edges": edges})
        s.add(v)
        await s.flush()
        vid = v.id
    run = await store.create_run(vid, request)
    for n in nodes:
        await store.create_node(run.id, n["key"], n["type"], n.get("config"))
    return run.id


def _edge(src, tgt):
    return {"source": src, "target": tgt, "sourceHandle": "request", "targetHandle": "request"}


async def test_input_chain_completes(store, db):
    nodes = [{"key": "a", "type": "input"}, {"key": "b", "type": "input"}, {"key": "c", "type": "input"}]
    edges = [_edge("a", "b"), _edge("b", "c")]
    run_id = await _seed_run(db, store, nodes, edges, {"text": "hi"})

    run = await step(run_id, store)
    assert run.status == "completed"
    assert {n.status for n in run.nodes} == {"done"}


async def test_unmet_dep_never_runs_and_reconciles_failed(store, db):
    # b has no handler → fails; c depends on b → never becomes ready.
    nodes = [{"key": "a", "type": "input"}, {"key": "b", "type": "nope"}, {"key": "c", "type": "input"}]
    edges = [_edge("a", "b"), _edge("b", "c")]
    run_id = await _seed_run(db, store, nodes, edges, {"text": "hi"})

    run = await step(run_id, store)
    by_key = {n.node_key: n for n in run.nodes}
    assert by_key["a"].status == "done"
    assert by_key["b"].status == "failed"
    assert by_key["c"].status == "pending"  # dep unmet → never ran
    assert run.status == "failed"
