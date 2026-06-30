"""Agent output validation — schema-as-data (Level 3, generic engine).

A node carries its output schema in `config["output_schema"]` as plain JSON. We build
a Pydantic validator from it at runtime, so a new workflow needs ZERO code — just data.
The engine never names a concrete schema. `Classification` stays as the default fallback
for nodes that don't specify one.

Field spec (per key):
    {"type": "str"|"int"|"float"|"bool"|"enum", "required": bool, "values": [...] (enum only)}
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, create_model

_PRIMITIVES = {"str": str, "int": int, "float": float, "bool": bool}


class Classification(BaseModel):
    """Default agent output for the support-triage seed graph."""

    label: Literal["bug", "billing", "unclear"]
    reply: str | None = None


def _field(spec: dict):
    if spec.get("type") == "enum":
        typ = Literal[tuple(spec["values"])]  # type: ignore # closed set → real validation
    else:
        typ = _PRIMITIVES[spec.get("type", "str")]
    if spec.get("required", False):
        return (typ, ...)
    return (typ | None, None)


@lru_cache(maxsize=128)
def _build_cached(spec_json: str) -> type[BaseModel]:
    spec = json.loads(spec_json)
    fields = {name: _field(fs) for name, fs in spec.items()}
    return create_model("AgentOutput", **fields)


def build_model(spec: dict) -> type[BaseModel]:
    """Build (and cache) a Pydantic model from a JSON field spec."""
    return _build_cached(json.dumps(spec, sort_keys=True))


def model_for(config: dict) -> type[BaseModel]:
    """Pick the validator for an agent node: its data schema, else the default."""
    spec = config.get("output_schema")
    return build_model(spec) if spec else Classification
