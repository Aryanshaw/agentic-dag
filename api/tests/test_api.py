"""Phase 5 gate: execute / get / retry-precondition / approve through the API."""

import httpx
import pytest
import pytest_asyncio

from main import app
from models import Graph, GraphVersion
from routers.deps import get_store
from tests.helpers import edge


@pytest_asyncio.fixture
async def client(store):
    app.dependency_overrides[get_store] = lambda: store
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    app.dependency_overrides.clear()


async def _seed_graph(db, nodes, edges) -> str:
    async with db.session() as s:
        g = Graph(name="t")
        s.add(g)
        await s.flush()
        gid = g.id
        v = GraphVersion(graph_id=gid, version=1, definition={"nodes": nodes, "edges": edges})
        s.add(v)
        await s.flush()
    return gid


async def test_execute_input_chain(client, db):
    gid = await _seed_graph(
        db,
        [{"key": "a", "type": "input"}, {"key": "b", "type": "input"}],
        [edge("a", "b")],
    )
    r = await client.post(f"/runs/execute/{gid}", json={"request": {"text": "hi"}})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert {n["status"] for n in body["nodes"]} == {"done"}

    # GET round-trips
    g = await client.get(f"/runs/{body['id']}")
    assert g.json()["status"] == "completed"


async def test_retry_requires_failed(client, db):
    gid = await _seed_graph(db, [{"key": "a", "type": "input"}], [])
    body = (await client.post(f"/runs/execute/{gid}", json={"request": {}})).json()
    node_id = body["nodes"][0]["id"]  # status done
    r = await client.post(f"/nodes/{node_id}/retry")
    assert r.status_code == 409


async def test_approve_resumes(client, db):
    gid = await _seed_graph(
        db,
        [
            {"key": "in", "type": "input"},
            {"key": "appr", "type": "approval"},
            {"key": "final", "type": "input"},
        ],
        [edge("in", "appr"), edge("appr", "final")],
    )
    body = (await client.post(f"/runs/execute/{gid}", json={"request": {}})).json()
    assert body["status"] == "awaiting_approval"
    appr_id = next(n["id"] for n in body["nodes"] if n["node_key"] == "appr")

    r = await client.post(f"/nodes/{appr_id}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
