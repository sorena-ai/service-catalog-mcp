"""Stripe webhook handler — validates signature and processes events."""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/stripe", tags=["stripe"])

logger = logging.getLogger(__name__)


@router.post("/webhook")
async def stripe_webhook(request: Request):
    try:
        sig_header = request.headers.get("stripe-signature")
        if not sig_header:
            raise HTTPException(status_code=400, detail="Missing stripe-signature header")

        payload = await request.body()

        from api.stripe import get_stripe_client
        result, status_code = get_stripe_client().handle_webhook_event(payload, sig_header)

        if status_code == 200:
            return JSONResponse(content={"received": True})

        logger.error("Webhook processing failed: %s", result)
        raise HTTPException(status_code=400, detail="Webhook processing failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Webhook error: %s", e)
        raise HTTPException(status_code=400, detail="Webhook processing failed")
