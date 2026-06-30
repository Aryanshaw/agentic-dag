"""API surface (LLD §9). Every mutating endpoint ends by calling step() and
returning the refreshed run — the re-entrant stepper surfaced to the client.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from engine.executor import step
from engine.store import Store
from models import NodeRun, Run
from routers.deps import get_store

router = APIRouter()


# ── serialization ────────────────────────────────────────────────────────
def _node_dict(n: NodeRun) -> dict:
    return {
        "id": n.id,
        "node_key": n.node_key,
        "type": n.type,
        "status": n.status,
        "input": n.input_json,
        "output": n.output_json,
        "error": n.error,
        "attempts": n.attempts,
        "logs": [
            {"ts": log.ts, "level": log.level, "message": log.message, "data": log.data}
            for log in sorted(n.logs, key=lambda x: x.ts)
        ],
    }


def _run_dict(run: Run) -> dict:
    return {
        "id": run.id,
        "status": run.status,
        "request": run.request,
        "nodes": [_node_dict(n) for n in sorted(run.nodes, key=lambda x: x.created_at)],
    }


async def _run_response(run_id: str, store: Store) -> dict:
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return _run_dict(run)


# ── endpoints ────────────────────────────────────────────────────────────
@router.get("/graphs")
async def list_graphs(store: Store = Depends(get_store)) -> list[dict]:
    graphs = await store.list_graphs()
    return [{"id": g.id, "name": g.name, "latest_version": g.latest_version} for g in graphs]


@router.post("/runs/execute/{graph_id}")
async def execute(graph_id: str, body: dict, store: Store = Depends(get_store)) -> dict:
    version = await store.get_latest_version(graph_id)
    if version is None:
        raise HTTPException(404, "graph not found")
    request = body.get("request", body)
    run = await store.create_run(version.id, request)
    for n in version.definition["nodes"]:
        await store.create_node(run.id, n["key"], n["type"], n.get("config"))
    await step(run.id, store)
    return await _run_response(run.id, store)


@router.get("/runs/{run_id}")
async def get_run(run_id: str, store: Store = Depends(get_store)) -> dict:
    return await _run_response(run_id, store)


async def _node_or_404(node_id: str, store: Store) -> NodeRun:
    node = await store.get_node(node_id)
    if node is None:
        raise HTTPException(404, "node not found")
    return node


@router.post("/nodes/{node_id}/retry")
async def retry(node_id: str, store: Store = Depends(get_store)) -> dict:
    node = await _node_or_404(node_id, store)
    if node.status != "failed":
        raise HTTPException(409, f"can only retry a failed node (is {node.status})")
    await store.incr_attempts(node.id)
    await store.set_status(node.id, "pending")  # failed → pending
    await step(node.run_id, store)
    return await _run_response(node.run_id, store)


@router.post("/nodes/{node_id}/approve")
async def approve(node_id: str, store: Store = Depends(get_store)) -> dict:
    node = await _node_or_404(node_id, store)
    if node.status != "awaiting_approval":
        raise HTTPException(409, f"node is not awaiting approval (is {node.status})")
    await store.set_status(node.id, "done")  # awaiting_approval → done
    await store.log(node.id, "info", "approved")
    await step(node.run_id, store)
    return await _run_response(node.run_id, store)


@router.post("/nodes/{node_id}/reject")
async def reject(node_id: str, body: dict | None = None, store: Store = Depends(get_store)) -> dict:
    node = await _node_or_404(node_id, store)
    if node.status != "awaiting_approval":
        raise HTTPException(409, f"node is not awaiting approval (is {node.status})")
    reason = (body or {}).get("reason", "rejected by reviewer")
    await store.set_status(node.id, "failed")  # awaiting_approval → failed
    await store.set_error(node.id, reason)
    await store.log(node.id, "error", f"rejected: {reason}")
    await step(node.run_id, store)  # reconciles run → failed
    return await _run_response(node.run_id, store)
