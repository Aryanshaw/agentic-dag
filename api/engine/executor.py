"""The executor — stateless, re-entrant readiness loop (LLD §4, HLD L3).

step() runs only when an endpoint calls it (no daemon). It re-derives everything
from persisted state, so retry and resume are the same operation: re-run the loop.
"""

from __future__ import annotations

from engine.graph import build_input, deps_of
from engine.registry import REGISTRY
from engine.store import Store

# terminal-resolved: readiness treats these identically (LLD §2)
RESOLVED = ("done", "skipped")


async def step(run_id: str, store: Store):
    """Run every node whose deps are resolved, until none are ready."""
    edges = (await store.get_definition(run_id))["edges"]

    while True:
        nodes = await store.get_nodes(run_id)
        by_key = {n.node_key: n for n in nodes}
        ready = [
            n
            for n in nodes
            if n.status == "pending"
            and all(by_key[d].status in RESOLVED for d in deps_of(n.node_key, edges))
        ]
        if not ready:
            break

        for n in ready:
            inp = build_input(n.node_key, edges, by_key)
            await store.set_input(n.id, inp)
            await store.set_status(n.id, "running")
            await store.log(n.id, "info", "start", inp)
            try:
                handler = REGISTRY.get(n.type)
                if handler is None:
                    raise ValueError(f"no handler for node type {n.type!r}")
                out = await handler(n, inp, store)
                fresh = await store.get_node(n.id)
                if fresh.status == "running":  # handler didn't park/skip itself
                    if out is not None:
                        await store.set_output(n.id, out)
                    await store.set_status(n.id, "done")
            except Exception as e:  # noqa: BLE001 — any handler error → node failed
                await store.set_error(n.id, str(e))
                await store.set_status(n.id, "failed")
                await store.log(n.id, "error", str(e))

    await reconcile_run_status(run_id, store)
    return await store.get_run(run_id)


async def reconcile_run_status(run_id: str, store: Store) -> str:
    """Derive the run's terminal/blocked status from its nodes."""
    nodes = await store.get_nodes(run_id)
    statuses = {n.status for n in nodes}
    if "failed" in statuses:
        status = "failed"
    elif "awaiting_approval" in statuses:
        status = "awaiting_approval"
    elif statuses <= set(RESOLVED):
        status = "completed"
    else:
        status = "running"
    await store.set_run_status(run_id, status)
    return status
