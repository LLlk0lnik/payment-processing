import asyncio
import random
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select

from app.db import Session
from app.models import Payment


async def emulate_gateway() -> str:
    await asyncio.sleep(random.uniform(2, 5))
    return "succeeded" if random.random() < 0.9 else "failed"


async def process_payment(payment_id: UUID, client: httpx.AsyncClient) -> None:
    # Commit the gateway result before sending HTTP so retries reuse the same outcome.
    async with Session() as session, session.begin():
        payment = (
            await session.execute(select(Payment).where(Payment.id == payment_id).with_for_update())
        ).scalar_one()
        if payment.status == "pending":
            payment.status = await emulate_gateway()
            payment.processed_at = datetime.now(UTC)

    async with Session() as session, session.begin():
        payment = (
            await session.execute(select(Payment).where(Payment.id == payment_id).with_for_update())
        ).scalar_one()
        if payment.webhook_delivered_at is not None:
            return
        payload = {
            "payment_id": str(payment.id),
            "amount": str(payment.amount),
            "currency": payment.currency,
            "status": payment.status,
            "metadata": payment.payment_metadata,
            "processed_at": payment.processed_at.isoformat(),
        }
        response = await client.post(
            payment.webhook_url,
            json=payload,
            headers={"Idempotency-Key": str(payment.id)},
        )
        response.raise_for_status()
        payment.webhook_delivered_at = datetime.now(UTC)
