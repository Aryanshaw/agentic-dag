"""Phase 3 gate: branch-skip, tool idempotency, approval park."""

from engine import mocks
from engine.executor import step
from engine.handlers import tool_handler
from tests.helpers import edge, seed_run


async def test_branch_skips_losing_paths(store, db):
    # in(label) -> branch -> {bug,billing,approval} -> final ; billing wins.
    nodes = [
        {"key": "in", "type": "input"},
        {"key": "branch", "type": "branch"},
        {"key": "bug", "type": "input"},
        {"key": "billing", "type": "input"},
        {"key": "approval", "type": "input"},
        {"key": "final", "type": "input"},
    ]
    edges = [
        edge("in", "branch", sh="label", th="label"),
        edge("branch", "bug", sh="label", th="label", condition="bug"),
        edge("branch", "billing", sh="label", th="label", condition="billing"),
        edge("branch", "approval", sh="label", th="label", condition="unclear"),
        edge("bug", "final"),
        edge("billing", "final"),
        edge("approval", "final"),
    ]
    run_id = await seed_run(db, store, nodes, edges, {"label": "billing"})

    run = await step(run_id, store)
    by_key = {n.node_key: n for n in run.nodes}
    assert by_key["bug"].status == "skipped"
    assert by_key["approval"].status == "skipped"
    assert by_key["billing"].status == "done"
    assert by_key["final"].status == "done"
    assert run.status == "completed"


async def test_tool_idempotent_retry(store, db):
    mocks.reset()
    nodes = [
        {"key": "in", "type": "input"},
        {"key": "tool", "type": "tool", "config": {"tool": "linear"}},
    ]
    edges = [edge("in", "tool", sh="text", th="text")]
    run_id = await seed_run(db, store, nodes, edges, {"text": "app crashes"})

    run = await step(run_id, store)
    tool_node = next(n for n in run.nodes if n.node_key == "tool")
    first = tool_node.output_json
    assert first["ticket_id"] == "LIN-1"

    # retry the SAME node a second time → cache hit, no new side-effect
    second = await tool_handler(tool_node, {"text": "app crashes"}, store)
    assert second == first
    assert mocks.created_count(f"{run_id}:tool") == 1  # exactly one side-effect


async def test_approval_parks(store, db):
    nodes = [
        {"key": "in", "type": "input"},
        {"key": "approval", "type": "approval"},
    ]
    edges = [edge("in", "approval")]
    run_id = await seed_run(db, store, nodes, edges, {"text": "vague"})

    run = await step(run_id, store)
    by_key = {n.node_key: n for n in run.nodes}
    assert by_key["approval"].status == "awaiting_approval"
    assert run.status == "awaiting_approval"
