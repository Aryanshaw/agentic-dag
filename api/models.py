"""SQLAlchemy tables for the agentic DAG engine (LLD §1).

Definition vs instance: graphs ──< graph_versions ──< runs ──< node_runs ──< node_logs.
Deps are never stored — derived from edges in the version definition.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ponytail: SQLite has no native uuid/timestamptz — String hex + DateTime cover it.
class Graph(Base):
    __tablename__ = "graphs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    versions: Mapped[list[GraphVersion]] = relationship(back_populates="graph")


class GraphVersion(Base):
    __tablename__ = "graph_versions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    graph_id: Mapped[str] = mapped_column(ForeignKey("graphs.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)

    graph: Mapped[Graph] = relationship(back_populates="versions")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    graph_version_id: Mapped[str] = mapped_column(
        ForeignKey("graph_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, default="running")
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    nodes: Mapped[list[NodeRun]] = relationship(back_populates="run")


class NodeRun(Base):
    __tablename__ = "node_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    node_key: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)

    run: Mapped[Run] = relationship(back_populates="nodes")
    logs: Mapped[list[NodeLog]] = relationship(back_populates="node_run")


class NodeLog(Base):
    __tablename__ = "node_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    node_run_id: Mapped[str] = mapped_column(ForeignKey("node_runs.id"), nullable=False)
    ts: Mapped[datetime] = mapped_column(default=_now)
    level: Mapped[str] = mapped_column(String, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    node_run: Mapped[NodeRun] = relationship(back_populates="logs")
