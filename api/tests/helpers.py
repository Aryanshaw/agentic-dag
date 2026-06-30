"""Shared test helpers: seed a graph_version + run + node_runs."""

from models import Graph, GraphVersion


async def seed_run(db, store, nodes: list[dict], edges: list[dict], request: dict) -> str:
    async with db.session() as s:
        g = Graph(name="t")
        s.add(g)
        await s.flush()
        v = GraphVersion(
            graph_id=g.id, version=1, definition={"nodes": nodes, "edges": edges}
        )
        s.add(v)
        await s.flush()
        vid = v.id
    run = await store.create_run(vid, request)
    for n in nodes:
        await store.create_node(run.id, n["key"], n["type"], n.get("config"))
    return run.id


def edge(src, tgt, sh="request", th="request", condition=None):
    e = {"source": src, "target": tgt, "sourceHandle": sh, "targetHandle": th}
    if condition is not None:
        e["condition"] = condition
    return e
