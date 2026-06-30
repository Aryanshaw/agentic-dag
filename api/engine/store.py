"""Persistence interface — the ONLY place that touches SQL (HLD L2).

The executor and handlers stay pure by going through this. Each method opens its
own session and commits, so every write is durable before the caller returns
(persist-before-return is a hard requirement for idempotency).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config.db import Database
from models import NodeLog, NodeRun, Run

# Node state machine (LLD §2). Enforced in set_status.
ALLOWED_TRANSITIONS: set[tuple[str, str]] = {
    ("pending", "running"),
    ("running", "done"),
    ("running", "failed"),
    ("running", "awaiting_approval"),
    ("failed", "pending"),  # retry
    ("awaiting_approval", "done"),  # approve
    ("awaiting_approval", "failed"),  # reject
    ("pending", "skipped"),  # branch killed this path
}


class Store:
    def __init__(self, db: Database):
        self.db = db

    # ── runs ────────────────────────────────────────────────────────────
    async def create_run(self, graph_version_id: str, request: dict) -> Run:
        async with self.db.session() as s:
            run = Run(graph_version_id=graph_version_id, request=request, status="running")
            s.add(run)
            await s.flush()
            await s.refresh(run)
            s.expunge(run)
            return run

    async def get_run(self, run_id: str) -> Run | None:
        async with self.db.session() as s:
            res = await s.execute(
                select(Run)
                .where(Run.id == run_id)
                .options(selectinload(Run.nodes).selectinload(NodeRun.logs))
            )
            return res.scalar_one_or_none()

    async def set_run_status(self, run_id: str, status: str) -> None:
        async with self.db.session() as s:
            run = await s.get(Run, run_id)
            run.status = status

    # ── nodes ───────────────────────────────────────────────────────────
    async def create_node(
        self, run_id: str, node_key: str, type: str, config: dict | None = None
    ) -> NodeRun:
        async with self.db.session() as s:
            node = NodeRun(
                run_id=run_id, node_key=node_key, type=type, config=config or {}
            )
            s.add(node)
            await s.flush()
            await s.refresh(node)
            s.expunge(node)
            return node

    async def get_nodes(self, run_id: str) -> list[NodeRun]:
        async with self.db.session() as s:
            res = await s.execute(select(NodeRun).where(NodeRun.run_id == run_id))
            return list(res.scalars().all())

    async def get_node(self, node_id: str) -> NodeRun | None:
        async with self.db.session() as s:
            return await s.get(NodeRun, node_id)

    async def set_status(self, node_id: str, status: str) -> None:
        async with self.db.session() as s:
            node = await s.get(NodeRun, node_id)
            if (node.status, status) not in ALLOWED_TRANSITIONS:
                raise ValueError(
                    f"illegal node transition {node.status!r} -> {status!r}"
                )
            node.status = status

    async def set_input(self, node_id: str, input_json: dict) -> None:
        async with self.db.session() as s:
            node = await s.get(NodeRun, node_id)
            node.input_json = input_json

    async def set_output(self, node_id: str, output_json: dict) -> None:
        async with self.db.session() as s:
            node = await s.get(NodeRun, node_id)
            node.output_json = output_json

    async def set_error(self, node_id: str, error: str) -> None:
        async with self.db.session() as s:
            node = await s.get(NodeRun, node_id)
            node.error = error

    async def incr_attempts(self, node_id: str) -> None:
        async with self.db.session() as s:
            node = await s.get(NodeRun, node_id)
            node.attempts += 1

    async def set_idempotency_key(self, node_id: str, key: str) -> None:
        async with self.db.session() as s:
            node = await s.get(NodeRun, node_id)
            node.idempotency_key = key

    # ── logs ────────────────────────────────────────────────────────────
    async def log(
        self, node_id: str, level: str, message: str, data: dict | None = None
    ) -> None:
        async with self.db.session() as s:
            s.add(NodeLog(node_run_id=node_id, level=level, message=message, data=data))
