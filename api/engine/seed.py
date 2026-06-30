"""Seed the support-triage graph on startup (Phase 7).

One graphs + graph_versions row for the assignment workflow. Idempotent: skips if a
graph with the same name already exists. Validates the definition is a DAG first.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from config.db import Database
from config.logger import get_logger
from engine.graph import is_dag
from models import Graph, GraphVersion

logger = get_logger(__name__)

_SEED_PATH = Path(__file__).resolve().parent.parent / "seeds" / "support_graph.json"


def load_support_def() -> dict:
    return json.loads(_SEED_PATH.read_text())


async def seed_support_graph(db: Database) -> str:
    """Insert the seed graph + version if absent. Returns the graph id."""
    spec = load_support_def()
    definition = {"nodes": spec["nodes"], "edges": spec["edges"]}
    if not is_dag(definition["nodes"], definition["edges"]):
        raise ValueError("seed graph is not a DAG")

    async with db.session() as s:
        existing = await s.execute(select(Graph).where(Graph.name == spec["name"]))
        graph = existing.scalar_one_or_none()
        if graph is not None:
            return graph.id
        graph = Graph(name=spec["name"], latest_version=1)
        s.add(graph)
        await s.flush()
        s.add(GraphVersion(graph_id=graph.id, version=1, definition=definition))
        logger.info("Seeded support graph %s", graph.id)
        return graph.id
