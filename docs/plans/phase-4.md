# Phase 4 Plan — Agent node (Groq)

## Files
- `api/engine/schemas.py` — **schema-as-data (Level 3)**. `build_model(spec)` builds a Pydantic validator at runtime from a JSON field spec in `config["output_schema"]` (via `create_model`). `model_for(config)` returns that, or `Classification` default. Engine names no concrete schema; a new workflow ships its schema as data, zero code.
- `api/agent/__init__.py`, `api/agent/classify.py` — `AsyncGroq` call (`llama-3.3-70b-versatile`), `response_format=json_object`, system prompt forcing `{label, reply}`. Loads `GROQ_API_KEY` via `load_dotenv()`. Returns raw JSON string.
- `api/engine/handlers.py` — `agent_handler`: `raw = await classify(text, node.config.get("prompt"))` → `Classification.model_validate_json(raw)` (validate BEFORE return); `ValidationError` → log + raise → node `failed`. Returns `result.model_dump()`.
- `api/engine/registry.py` — register `agent`.
- `api/tests/test_agent.py`.

## Validation-failure seam (scenario 4, no stubs)
- Normal nodes: default prompt → valid enum label.
- Bad-path node: `config["prompt"]` instructs an out-of-enum label (e.g. UPPERCASE). Real Groq call, JSON parses, Pydantic `Literal` rejects → `ValidationError` → `failed`, downstream blocked.

## Test (`test_agent.py`)
1. Deterministic (no network): `Classification.model_validate_json('{"label":"nonsense"}')` raises `ValidationError`; valid payload parses.
2. Real Groq: classify "I was double-charged" → label `billing` (marked, needs `GROQ_API_KEY`).
3. Real Groq end-to-end: agent node with enum-breaking prompt → node `failed`.

## Gate
`pytest tests/test_agent.py` green (real-Groq tests require `GROQ_API_KEY`, present in `api/.env`).
