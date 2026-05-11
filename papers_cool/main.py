"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import db, scheduler
from .config import get_settings
from .routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init_db()
    sched = None
    if not settings.disable_scheduler:
        sched = scheduler.start_scheduler(settings.categories)
    try:
        yield
    finally:
        if sched is not None:
            try:
                sched.shutdown(wait=False)
            except Exception:
                pass


app = FastAPI(title="papers.cool (local)", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
