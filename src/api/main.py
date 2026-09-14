import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO), stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING)


def _build_scheduler():
    from pathlib import Path
    from sdk.workspace import Workspace
    from sdk.indexer import IndexingScheduler
    base = Path(os.getenv("WORKSPACE_BASE_DIR", "/var/workspaces"))
    ws = Workspace(local=False, base=base)
    return IndexingScheduler(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from lib.async_utils import set_main_event_loop
    set_main_event_loop(asyncio.get_running_loop())
    scheduler = _build_scheduler()
    app.state.scheduler = scheduler
    yield
    await scheduler.shutdown()


app = FastAPI(title="Service Catalog API", lifespan=lifespan)

from api.routes import github, health, indexing, stripe  # noqa: E402

app.include_router(health.router)
app.include_router(github.router)
app.include_router(indexing.router)
app.include_router(stripe.router)
