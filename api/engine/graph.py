"""Graph primitives — pure functions over the definition JSON, no DB (LLD §3).

Edge shape: {source, target, sourceHandle, targetHandle, condition?}.
Deps are derived from edges, never stored.
"""

from __future__ import annotations

Edge = dict
Node = dict


def deps_of(node_key: str, edges: list[Edge]) -> list[str]:
    """Upstream node_keys this node depends on (sources of incoming edges)."""
    return [e["source"] for e in edges if e["target"] == node_key]


def outgoing_edges(node_key: str, edges: list[Edge]) -> list[Edge]:
    return [e for e in edges if e["source"] == node_key]


def is_dag(nodes: list[Node], edges: list[Edge]) -> bool:
    """Kahn's algorithm: peel in-degree-0 nodes; leftover nodes ⇒ cycle."""
    indeg = {n["key"]: 0 for n in nodes}
    for e in edges:
        indeg[e["target"]] += 1
    queue = [k for k, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        k = queue.pop()
        seen += 1
        for e in (x for x in edges if x["source"] == k):
            indeg[e["target"]] -= 1
            if indeg[e["target"]] == 0:
                queue.append(e["target"])
    return seen == len(nodes)


def build_input(node_key: str, edges: list[Edge], nodes_by_key: dict) -> dict:
    """Resolve a node's runtime input by walking incoming edges.

    nodes_by_key: {node_key: NodeRun}. Maps each upstream output_json[sourceHandle]
    onto this node's input[targetHandle].
    """
    inp: dict = {}
    for e in edges:
        if e["target"] == node_key:
            up = nodes_by_key.get(e["source"])
            out = (getattr(up, "output_json", None) or {}) if up is not None else {}
            inp[e["targetHandle"]] = out.get(e["sourceHandle"])
    return inp
