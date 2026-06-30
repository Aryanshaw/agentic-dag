"""SQLite database setup using SQLAlchemy async."""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config.logger import get_logger

load_dotenv()
logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is not set.")
        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init(self) -> None:
        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                await conn.execute(text("SELECT 1"))
                logger.info("Database connection verified.")
                await conn.run_sync(Base.metadata.create_all)
                logger.info("Database initialization completed.")
        except Exception:
            logger.exception("Database initialization failed.")
            raise

    async def close(self) -> None:
        await self.engine.dispose()
        logger.info("Database connection closed.")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


DATABASE_URL = os.getenv("DATABASE_URL")


@asynccontextmanager
async def connect_db() -> AsyncGenerator[Database, None]:
    db = Database(DATABASE_URL)
    await db.init()
    try:
        yield db
    finally:
        await db.close()
