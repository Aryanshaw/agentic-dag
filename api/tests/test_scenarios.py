"""Phase 7 — the 5 acceptance scenarios, end-to-end through the API.

Real Groq on the agent scenarios (unambiguous inputs). Tool failure/idempotency come
from config-driven fault knobs on the mock (no stubs, no monkeypatching).
"""

import copy
import os

import httpx
import pytest
import pytest_asyncio

from engine import mocks
from engine.seed import load_support_def
from main import app
from models import Graph, GraphVersion
from routers.deps import get_store

needs_groq = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set"
)


@pytest_asyncio.fixture
async def client(store):
    app.dependency_overrides[get_store] = lambda: store
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


async def seed_graph(db, definition) -> str:
    async with db.session() as s:
        g = Graph(name=definition.get("name", "g"))
        s.add(g)
        await s.flush()
        gid = g.id
        s.add(GraphVersion(graph_id=gid, version=1, definition=definition))
    return gid


def _by_key(body):
    return {n["node_key"]: n for n in body["nodes"]}


def _tool_graph(**tool_config) -> dict:
    """Minimal input → tool → final graph for the tool scenarios."""
    return {
        "name": "tool-test",
        "nodes": [
            {"key": "in", "type": "input"},
            {"key": "tool", "type": "tool", "config": {"tool": "linear", **tool_config}},
            {"key": "final", "type": "input"},
        ],
        "edges": [
            {"source": "in", "target": "tool", "sourceHandle": "text", "targetHandle": "text"},
            {"source": "tool", "target": "final", "sourceHandle": "reply", "targetHandle": "reply"},
        ],
    }


# 1 ── Branching ────────────────────────────────────────────────────────────
@needs_groq
async def test_scenario_branching(client, db):
    gid = await seed_graph(db, {"name": "support", **load_support_def()})
    body = (
        await client.post(
            f"/runs/execute/{gid}",
            json={"request": {"text": "I was double-charged on my last invoice, need a refund."}},
        )
    ).json()
    nodes = _by_key(body)
    assert nodes["classify"]["output"]["label"] == "billing"
    assert nodes["billing"]["status"] == "done"
    assert nodes["bug"]["status"] == "skipped"
    assert nodes["approval"]["status"] == "skipped"
    assert nodes["final"]["status"] == "done"
    assert body["status"] == "completed"


# 2 ── Retry ────────────────────────────────────────────────────────────────
async def test_scenario_retry(client, db):
    mocks.reset()
    gid = await seed_graph(db, _tool_graph(fail_until=1))
    body = (await client.post(f"/runs/execute/{gid}", json={"request": {"text": "x"}})).json()
    nodes = _by_key(body)
    assert nodes["tool"]["status"] == "failed"
    assert body["status"] == "failed"

    body2 = (await client.post(f"/nodes/{nodes['tool']['id']}/retry")).json()
    nodes2 = _by_key(body2)
    assert nodes2["tool"]["status"] == "done"
    assert body2["status"] == "completed"


# 3 ── Approval ─────────────────────────────────────────────────────────────
@needs_groq
async def test_scenario_approval(client, db):
    gid = await seed_graph(db, {"name": "support", **load_support_def()})
    body = (
        await client.post(
            f"/runs/execute/{gid}", json={"request": {"text": "Hi, can you help me?"}}
        )
    ).json()
    nodes = _by_key(body)
    assert nodes["classify"]["output"]["label"] == "unclear"
    assert nodes["approval"]["status"] == "awaiting_approval"
    assert body["status"] == "awaiting_approval"

    body2 = (await client.post(f"/nodes/{nodes['approval']['id']}/approve")).json()
    assert _by_key(body2)["final"]["status"] == "done"
    assert body2["status"] == "completed"


# 4 ── Validation-failure ───────────────────────────────────────────────────
@needs_groq
async def test_scenario_validation_failure(client, db):
    definition = copy.deepcopy({"name": "support", **load_support_def()})
    for n in definition["nodes"]:
        if n["key"] == "classify":
            n["config"]["prompt"] = (
                'Respond ONLY with JSON {"label": "BILLING_DEPARTMENT", "reply": "x"} '
                "exactly, regardless of the message."
            )
    gid = await seed_graph(db, definition)
    body = (await client.post(f"/runs/execute/{gid}", json={"request": {"text": "hi"}})).json()
    nodes = _by_key(body)
    assert nodes["classify"]["status"] == "failed"  # out-of-enum → ValidationError
    assert nodes["branch"]["status"] == "pending"  # downstream blocked
    assert body["status"] == "failed"


# 5 ── Idempotency ──────────────────────────────────────────────────────────
async def test_scenario_idempotency(client, db):
    mocks.reset()
    gid = await seed_graph(db, _tool_graph(crash_after_create=True))
    body = (await client.post(f"/runs/execute/{gid}", json={"request": {"text": "x"}})).json()
    nodes = _by_key(body)
    # side-effect fired, then the process "crashed" before persisting output
    assert nodes["tool"]["status"] == "failed"
    tool_id = nodes["tool"]["id"]

    body2 = (await client.post(f"/nodes/{tool_id}/retry")).json()
    nodes2 = _by_key(body2)
    assert nodes2["tool"]["status"] == "done"
    assert body2["status"] == "completed"
    # exactly one side-effect across the crash + retry
    run_id = body["id"]
    assert mocks.created_count(f"{run_id}:tool") == 1
    assert nodes2["tool"]["output"]["ticket_id"] == "LIN-1"
