"""Phase 1 gate: deps_of, is_dag (Kahn), build_input."""

from types import SimpleNamespace

from engine.graph import build_input, deps_of, is_dag, outgoing_edges


def _edge(src, tgt, sh="out", th="in", condition=None):
    e = {"source": src, "target": tgt, "sourceHandle": sh, "targetHandle": th}
    if condition is not None:
        e["condition"] = condition
    return e


def test_linear_deps_and_dag():
    nodes = [{"key": "a"}, {"key": "b"}, {"key": "c"}]
    edges = [_edge("a", "b"), _edge("b", "c")]
    assert deps_of("b", edges) == ["a"]
    assert deps_of("c", edges) == ["b"]
    assert deps_of("a", edges) == []
    assert is_dag(nodes, edges) is True


def test_branching_deps():
    nodes = [{"key": k} for k in ("classify", "branch", "bug", "billing", "approval", "final")]
    edges = [
        _edge("classify", "branch"),
        _edge("branch", "bug", condition="bug"),
        _edge("branch", "billing", condition="billing"),
        _edge("branch", "approval", condition="unclear"),
        _edge("bug", "final"),
        _edge("billing", "final"),
        _edge("approval", "final"),
    ]
    assert deps_of("branch", edges) == ["classify"]
    assert sorted(deps_of("final", edges)) == ["approval", "billing", "bug"]
    assert {e["target"] for e in outgoing_edges("branch", edges)} == {"bug", "billing", "approval"}
    assert is_dag(nodes, edges) is True


def test_cycle_rejected():
    nodes = [{"key": "a"}, {"key": "b"}]
    edges = [_edge("a", "b"), _edge("b", "a")]
    assert is_dag(nodes, edges) is False


def test_build_input_maps_handles():
    up = SimpleNamespace(output_json={"label": "billing"})
    nodes_by_key = {"classify": up}
    edges = [_edge("classify", "branch", sh="label", th="label")]
    assert build_input("branch", edges, nodes_by_key) == {"label": "billing"}


def test_build_input_missing_upstream_output():
    up = SimpleNamespace(output_json=None)
    edges = [_edge("classify", "branch", sh="label", th="label")]
    assert build_input("branch", edges, {"classify": up}) == {"label": None}
