from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.services.memory_service import MemoryService
from app.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Inquira AI -- initializing SQLite memory store")
    await MemoryService().init_db()
    yield
    logger.info("Shutting down Inquira AI")


app = FastAPI(
    title="Inquira AI",
    description="Autonomous Research. Verified Insights.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP scope; tighten for real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
