"""Node handlers. Each: async (node, inp, store) -> dict | None (LLD §5).

Pure-ish: take input, return dict, raise on failure. Side-effects go through store.
Phase 2 ships `input`; branch/tool/approval land in Phase 3, agent in Phase 4.
"""

from __future__ import annotations

from engine.graph import outgoing_edges
from engine.mocks import TOOLS
from models import NodeRun


async def input_handler(node: NodeRun, inp: dict, store) -> dict:
    """Entry node: seeds shared state from the run's request. Always done.

    Output spreads the request so downstream edges can pull fields by handle
    (e.g. sourceHandle "text"), and keeps a `request` key for the whole payload.
    """
    run = await store.get_run(node.run_id)
    req = run.request if isinstance(run.request, dict) else {"value": run.request}
    return {**req, "request": run.request}


async def branch_handler(node: NodeRun, inp: dict, store) -> dict:
    """Route on label: mark every outgoing edge whose condition ≠ label `skipped`.

    Readiness counts `skipped` as resolved, so the join node (`final`) still fires
    off the one live path. No node deletion — fully recoverable (LLD §8).
    """
    label = inp.get("label")
    edges = (await store.get_definition(node.run_id))["edges"]
    for e in outgoing_edges(node.node_key, edges):
        if e.get("condition") and e["condition"] != label:
            target = await store.get_node_by_key(node.run_id, e["target"])
            await store.set_status(target.id, "skipped")
            await store.log(node.id, "info", f"skipped dead path: {e['target']}")
    return {"label": label}


async def tool_handler(node: NodeRun, inp: dict, store) -> dict:
    """Idempotent mock side-effect. Persist output BEFORE returning (LLD §7)."""
    fresh = await store.get_node(node.id)
    if fresh.output_json is not None:  # already executed this run → replay cache
        await store.log(node.id, "info", "idempotent hit; skipping side-effect")
        return fresh.output_json

    key = f"{node.run_id}:{node.node_key}"  # stable across retries
    await store.set_idempotency_key(node.id, key)
    tool = TOOLS[node.config["tool"]]
    # Fault knobs live in the mock (an unreliable external system), opt-in per node.
    result = tool(
        inp,
        idem_key=key,
        fail_until=node.config.get("fail_until", 0),
        attempts=fresh.attempts,
        crash_after=node.config.get("crash_after_create", False),
    )
    await store.set_output(node.id, result)  # persist before return
    return result


async def approval_handler(node: NodeRun, inp: dict, store) -> None:
    """Human-in-the-loop: park the node; the executor halts here (LLD §5)."""
    await store.set_status(node.id, "awaiting_approval")
    await store.log(node.id, "info", "parked for human approval")
    return None
