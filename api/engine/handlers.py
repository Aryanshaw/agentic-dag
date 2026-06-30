"""Node handlers. Each: async (node, inp, store) -> dict | None (LLD §5).

Pure-ish: take input, return dict, raise on failure. Side-effects go through store.
Phase 2 ships `input`; branch/tool/approval land in Phase 3, agent in Phase 4.
"""

from __future__ import annotations

from models import NodeRun


async def input_handler(node: NodeRun, inp: dict, store) -> dict:
    """Entry node: seeds shared state from the run's request. Always done.

    Output spreads the request so downstream edges can pull fields by handle
    (e.g. sourceHandle "text"), and keeps a `request` key for the whole payload.
    """
    run = await store.get_run(node.run_id)
    req = run.request if isinstance(run.request, dict) else {"value": run.request}
    return {**req, "request": run.request}
