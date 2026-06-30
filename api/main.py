"""FastAPI backend entrypoint."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.db import DATABASE_URL, Database
from config.logger import get_logger
from routers.runs import router as runs_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(DATABASE_URL)
    await db.init()
    app.state.db = db
    logger.info("REST API startup complete.")
    yield
    await db.close()
    logger.info("REST API shutdown complete.")


app = FastAPI(title="Agentic DAG Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router)


@app.get("/")
async def root() -> dict:
    return {"message": "Agentic DAG engine is running"}


@app.get("/health")
async def health() -> dict:
    if not getattr(app.state, "db", None):
        raise HTTPException(status_code=503, detail="Database not ready")
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
