"""Shared fixtures: a throwaway file-backed SQLite DB + Store per test."""

import os
import tempfile

import pytest_asyncio

from config.db import Database
from engine.store import Store


@pytest_asyncio.fixture
async def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(f"sqlite+aiosqlite:///{path}")
    await database.init()  # create_all
    try:
        yield database
    finally:
        await database.close()
        os.unlink(path)


@pytest_asyncio.fixture
async def store(db):
    return Store(db)
