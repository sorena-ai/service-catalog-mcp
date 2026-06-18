"""Indexing status endpoint."""

import base64
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from sdk.indexer import progress

router = APIRouter(prefix="/indexing")


@router.get("/status")
async def indexing_status(state: str):
    try:
        user_id = base64.urlsafe_b64decode(state.encode()).decode()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid state parameter")

    snap = progress.snapshot(user_id)
    if snap is None:
        return JSONResponse({"phase": "starting"})

    return JSONResponse(snap)
