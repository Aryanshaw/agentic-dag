"""Phase 0 gate: insert + read-back, and set_status transition guard."""

import pytest

from models import Graph, GraphVersion


async def _seed_version(db) -> str:
    """Insert a graph + version directly, return the version id."""
    async with db.session() as s:
        g = Graph(name="t")
        s.add(g)
        await s.flush()
        v = GraphVersion(graph_id=g.id, version=1, definition={"nodes": [], "edges": []})
        s.add(v)
        await s.flush()
        return v.id


async def test_insert_and_readback(store, db):
    vid = await _seed_version(db)
    run = await store.create_run(vid, {"text": "hi"})
    node = await store.create_node(run.id, "input", "input", {"k": "v"})

    got = await store.get_run(run.id)
    assert got.request == {"text": "hi"}
    assert got.status == "running"

    nodes = await store.get_nodes(run.id)
    assert len(nodes) == 1
    assert nodes[0].node_key == "input"
    assert nodes[0].config == {"k": "v"}
    assert nodes[0].status == "pending"
    assert node.id == nodes[0].id


async def test_set_status_legal(store, db):
    vid = await _seed_version(db)
    run = await store.create_run(vid, {})
    node = await store.create_node(run.id, "input", "input")
    await store.set_status(node.id, "running")  # pending -> running, legal
    assert (await store.get_node(node.id)).status == "running"


async def test_set_status_illegal_rejected(store, db):
    vid = await _seed_version(db)
    run = await store.create_run(vid, {})
    node = await store.create_node(run.id, "input", "input")
    await store.set_status(node.id, "running")
    await store.set_status(node.id, "done")
    with pytest.raises(ValueError):
        await store.set_status(node.id, "running")  # done -> running, illegal
