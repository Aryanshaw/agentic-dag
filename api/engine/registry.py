"""type → handler map (HLD L1). Adding a node type = registering one handler here.

Handler contract: async (node: NodeRun, inp: dict, store: Store) -> dict | None.
Return a dict to set output + mark done; park/skip self by calling store.set_status
inside the handler (executor leaves it alone if status != "running").
"""

from __future__ import annotations

from engine import handlers

REGISTRY = {
    "input": handlers.input_handler,
    "agent": handlers.agent_handler,
    "branch": handlers.branch_handler,
    "tool": handlers.tool_handler,
    "approval": handlers.approval_handler,
}
