from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import authenticate
from app.db import get_session
from app.models import OutboxEvent, Payment
from app.schemas import PaymentAccepted, PaymentCreate, PaymentDetail

router = APIRouter(prefix="/api/v1/payments", dependencies=[Depends(authenticate)])
Database = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=PaymentAccepted, status_code=202)
async def create_payment(
    body: PaymentCreate,
    response: Response,
    session: Database,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=255)],
):
    if not idempotency_key.strip():
        raise HTTPException(status_code=422, detail="Idempotency-Key cannot be blank")
    fingerprint = body.fingerprint()
    async with session.begin():
        payment_id = uuid4()
        result = await session.execute(
            insert(Payment)
            .values(
                id=payment_id,
                amount=body.amount,
                currency=body.currency,
                description=body.description,
                payment_metadata=body.metadata,
                webhook_url=str(body.webhook_url),
                idempotency_key=idempotency_key,
                request_hash=fingerprint,
            )
            .on_conflict_do_nothing(index_elements=[Payment.idempotency_key])
            .returning(Payment)
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            payment = (
                await session.execute(
                    select(Payment).where(Payment.idempotency_key == idempotency_key)
                )
            ).scalar_one()
            if payment.request_hash != fingerprint:
                raise HTTPException(409, "Idempotency-Key already used with a different request")
        else:
            session.add(OutboxEvent(payload={"payment_id": str(payment_id)}))
    response.headers["Location"] = f"/api/v1/payments/{payment.id}"
    return payment


@router.get("/{payment_id}", response_model=PaymentDetail)
async def get_payment(payment_id: UUID, session: Database):
    payment = await session.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment
