"""Mock external side-effects (Linear, invoice). Dedupe on idem_key (LLD §7).

These stand in for real integrations — and real integrations fail. The fault knobs
(`fail_until`, `crash_after`) model an unreliable external system; they are opt-in
per node config and off by default. They exist so the retry/idempotency scenarios run
through a real code path (SPEC bans stubs/monkeypatching), not as production behaviour.

Dedupe on idem_key is the partial-failure backstop: a crash after the side-effect but
before the caller persists output still yields exactly one effect on retry. `_created`
records distinct creations so tests can assert the effect fired once.
"""

from __future__ import annotations


class ExternalToolError(RuntimeError):
    """Simulated failure from the mock external system."""


_issues: dict[str, dict] = {}  # idem_key -> result
_invoices: dict[str, dict] = {}
_created: list[str] = []  # idem_keys for which a NEW side-effect actually fired


def reset() -> None:  # test helper
    _issues.clear()
    _invoices.clear()
    _created.clear()


def created_count(idem_key: str) -> int:
    return _created.count(idem_key)


def _run(store_dict, idem_key, make, fail_until, attempts, crash_after):
    if idem_key in store_dict:  # idempotent: already created this run → replay
        return store_dict[idem_key]
    if attempts < fail_until:  # external system down → no side-effect yet
        raise ExternalToolError("external system unavailable")
    result = make()  # the side-effect
    _created.append(idem_key)
    store_dict[idem_key] = result
    if crash_after:  # died after the effect, before the caller could persist output
        raise ExternalToolError("crashed after side-effect")
    return result


def mock_create_linear_issue(inp, idem_key, fail_until=0, attempts=0, crash_after=False):
    return _run(
        _issues,
        idem_key,
        lambda: {
            "ticket_id": f"LIN-{len(_issues) + 1}",
            "reply": f"Logged a bug ticket for: {inp.get('text', '')}",
        },
        fail_until,
        attempts,
        crash_after,
    )


def mock_check_invoice(inp, idem_key, fail_until=0, attempts=0, crash_after=False):
    return _run(
        _invoices,
        idem_key,
        lambda: {
            "invoice": {"id": f"INV-{len(_invoices) + 1}", "status": "paid", "amount": 4200},
            "reply": f"Checked your invoice regarding: {inp.get('text', '')}",
        },
        fail_until,
        attempts,
        crash_after,
    )


TOOLS = {
    "linear": mock_create_linear_issue,
    "invoice": mock_check_invoice,
}
