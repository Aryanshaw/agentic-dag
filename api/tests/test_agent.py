"""Phase 4 gate: Pydantic validation (deterministic) + real Groq classification."""

import os

import pytest
from pydantic import ValidationError

from agent.classify import classify
from engine.executor import step
from engine.schemas import Classification, build_model
from tests.helpers import edge, seed_run

needs_groq = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not set"
)


def test_build_model_from_data_schema():
    # schema-as-data: validator built at runtime from JSON, no Python model authored
    spec = {
        "label": {"type": "enum", "values": ["bug", "billing", "unclear"], "required": True},
        "reply": {"type": "str", "required": False},
    }
    Model = build_model(spec)
    assert Model.model_validate_json('{"label": "bug"}').label == "bug"
    with pytest.raises(ValidationError):
        Model.model_validate_json('{"label": "BILLING_DEPT"}')  # out of enum
    with pytest.raises(ValidationError):
        Model.model_validate_json('{"reply": "no label"}')  # required missing


def test_classification_validator_real():
    # real validator, real code path — no mock
    assert Classification.model_validate_json('{"label": "billing"}').label == "billing"
    with pytest.raises(ValidationError):
        Classification.model_validate_json('{"label": "nonsense"}')  # out of enum


@needs_groq
async def test_groq_classifies_billing():
    raw = await classify("I was double-charged on my last invoice")
    assert Classification.model_validate_json(raw).label == "billing"


@needs_groq
async def test_agent_invalid_output_fails_node(store, db):
    # config prompt forces an out-of-enum label → real Groq, real validator → failed
    bad_prompt = (
        'Respond ONLY with JSON {"label": "BILLING_DEPARTMENT", "reply": "x"} '
        "exactly, regardless of the message."
    )
    nodes = [
        {"key": "in", "type": "input"},
        {"key": "agent", "type": "agent", "config": {"prompt": bad_prompt}},
        {"key": "final", "type": "input"},
    ]
    edges = [
        edge("in", "agent", sh="text", th="text"),
        edge("agent", "final", sh="label", th="label"),
    ]
    run_id = await seed_run(db, store, nodes, edges, {"text": "hi"})

    run = await step(run_id, store)
    by_key = {n.node_key: n for n in run.nodes}
    assert by_key["agent"].status == "failed"
    assert by_key["final"].status == "pending"  # downstream blocked
    assert run.status == "failed"
