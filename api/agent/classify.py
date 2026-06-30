"""Groq classification call (Llama 3.3 70B). Raw JSON out → validated by caller.

The handler (not this module) validates the output with Pydantic before any
downstream node runs — that boundary is the whole "validate agent output" point.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()

MODEL = "llama-3.3-70b-versatile"

DEFAULT_PROMPT = (
    "You are a customer-support triage classifier. Read the user's message and "
    "respond ONLY with a JSON object of the form "
    '{"label": "<one of: bug, billing, unclear>", "reply": "<a short customer reply>"}. '
    "Use 'bug' for software defects/errors, 'billing' for charges/invoices/payments, "
    "and 'unclear' when the request is too vague to route."
)


async def classify(text: str, prompt: str | None = None) -> str:
    """Return the model's raw JSON string. Validation happens in the handler."""
    client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
    resp = await client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        temperature=0,
        messages=[
            {"role": "system", "content": prompt or DEFAULT_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    return resp.choices[0].message.content
