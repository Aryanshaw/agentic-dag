"""FastAPI dependencies. get_store is overridden in tests with a temp-db store."""

from fastapi import Request

from engine.store import Store


def get_store(request: Request) -> Store:
    return Store(request.app.state.db)
