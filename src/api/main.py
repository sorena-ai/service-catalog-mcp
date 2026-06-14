import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO), stream=sys.stdout)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from lib.async_utils import set_main_event_loop
    set_main_event_loop(asyncio.get_running_loop())
    yield
    from sdk.indexer import indexing_scheduler
    await indexing_scheduler.shutdown()


app = FastAPI(title="Service Catalog API", lifespan=lifespan)

from api.routes import github, health, stripe  # noqa: E402

app.include_router(health.router)
app.include_router(github.router)
app.include_router(stripe.router)
