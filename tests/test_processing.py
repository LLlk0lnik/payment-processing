import os
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from faststream.rabbit import TestRabbitBroker as RabbitTestBroker
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import outbox, worker
from app.db import Base
from app.models import OutboxEvent, Payment
from app.services import processing

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set"
)


@pytest.fixture
async def database(monkeypatch):
    url = os.environ["TEST_DATABASE_URL"]
    admin_engine = create_async_engine(url)
    schema = f"test_{uuid4().hex}"
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(processing, "Session", sessions)
    monkeypatch.setattr(outbox, "Session", sessions)
    try:
        yield sessions
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


async def seed(sessions):
    payment_id = uuid4()
    event_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Payment(
                id=payment_id,
                amount=Decimal("10.00"),
                currency="RUB",
                description="order",
                payment_metadata={"order_id": 1},
                idempotency_key=str(payment_id),
                request_hash="a" * 64,
                webhook_url="http://client/webhook",
            )
        )
        session.add(OutboxEvent(id=event_id, payload={"payment_id": str(payment_id)}))
    return payment_id, event_id


@pytest.mark.parametrize("status", ["succeeded", "failed"])
async def test_gateway_result_survives_webhook_retry(database, monkeypatch, status):
    payment_id, _ = await seed(database)
    gateway = AsyncMock(return_value=status)
    monkeypatch.setattr(processing, "emulate_gateway", gateway)
    responses = [503, 204]
    received = []

    def webhook(request):
        received.append(request)
        return httpx.Response(responses.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(webhook)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await processing.process_payment(payment_id, client)
        async with database() as session:
            payment = await session.get(Payment, payment_id)
            assert payment.status == status
            assert payment.processed_at is not None
            assert payment.webhook_delivered_at is None
        await processing.process_payment(payment_id, client)
        await processing.process_payment(payment_id, client)
    gateway.assert_awaited_once()
    assert len(received) == 2
    assert received[0].headers["Idempotency-Key"] == str(payment_id)
    async with database() as session:
        assert (await session.get(Payment, payment_id)).webhook_delivered_at is not None


async def test_outbox_publish_failure_rolls_back(database):
    _, event_id = await seed(database)
    broker = AsyncMock()
    broker.publish.side_effect = ConnectionError("broker offline")
    with pytest.raises(ConnectionError):
        await outbox.publish_batch(broker)
    async with database() as session:
        assert (await session.get(OutboxEvent, event_id)).published_at is None
    broker.publish.side_effect = None
    assert await outbox.publish_batch(broker) == 1
    assert await outbox.publish_batch(broker) == 0
    async with database() as session:
        assert (await session.get(OutboxEvent, event_id)).published_at is not None


async def test_relay_to_consumer_and_duplicate_delivery(database, monkeypatch):
    payment_id, event_id = await seed(database)
    gateway = AsyncMock(return_value="succeeded")
    monkeypatch.setattr(processing, "emulate_gateway", gateway)
    requests = []

    def webhook(request):
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(webhook)) as client:
        monkeypatch.setattr(worker, "client", client)
        async with RabbitTestBroker(worker.broker):
            assert await outbox.publish_batch(worker.broker) == 1
            await worker.broker.publish({"payment_id": str(payment_id)}, queue=worker.queue)
    assert len(requests) == 1
    gateway.assert_awaited_once()
    async with database() as session:
        payment = await session.get(Payment, payment_id)
        assert payment.status == "succeeded"
        assert payment.webhook_delivered_at <= datetime.now(UTC)
        event = (
            await session.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))
        ).scalar_one()
        assert event.published_at is not None
