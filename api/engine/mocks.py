"""Mock external side-effects (Linear, invoice). Dedupe on idem_key (LLD §7).

These stand in for real integrations. Each keys on idem_key so a retry after a
crash-between-side-effect-and-persist still produces exactly one effect. `_created`
records distinct creations so tests can assert the side-effect ran once.
"""

from __future__ import annotations

_issues: dict[str, dict] = {}  # idem_key -> result
_invoices: dict[str, dict] = {}
_created: list[str] = []  # idem_keys for which a NEW side-effect actually fired


def reset() -> None:  # test helper
    _issues.clear()
    _invoices.clear()
    _created.clear()


def created_count(idem_key: str) -> int:
    return _created.count(idem_key)


def mock_create_linear_issue(inp: dict, idem_key: str) -> dict:
    if idem_key in _issues:
        return _issues[idem_key]
    _created.append(idem_key)
    result = {
        "ticket_id": f"LIN-{len(_issues) + 1}",
        "reply": f"Logged a bug ticket for: {inp.get('text', '')}",
    }
    _issues[idem_key] = result
    return result


def mock_check_invoice(inp: dict, idem_key: str) -> dict:
    if idem_key in _invoices:
        return _invoices[idem_key]
    _created.append(idem_key)
    result = {
        "invoice": {"id": f"INV-{len(_invoices) + 1}", "status": "paid", "amount": 4200},
        "reply": f"Checked your invoice regarding: {inp.get('text', '')}",
    }
    _invoices[idem_key] = result
    return result


TOOLS = {
    "linear": mock_create_linear_issue,
    "invoice": mock_check_invoice,
}
