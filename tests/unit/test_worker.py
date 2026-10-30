from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.messaging import consumer as worker
from app.messaging.topology import dead_queue, retry_queues


@pytest.mark.parametrize(
    "attempt,target", [(1, retry_queues[0]), (2, retry_queues[1]), (3, dead_queue)]
)
async def test_failure_is_published_to_next_queue(monkeypatch, attempt, target):
    process = AsyncMock(side_effect=RuntimeError("unavailable"))
    publish = AsyncMock()
    monkeypatch.setattr(worker, "process_payment", process)
    monkeypatch.setattr(worker, "client", object())
    monkeypatch.setattr(worker.broker, "publish", publish)
    body = {"payment_id": str(uuid4())}
    message = AsyncMock(headers={"attempt": attempt})
    await worker.consume(body, message)
    assert publish.await_args.kwargs["queue"] == target
    assert publish.await_args.kwargs["persist"] is True
    assert publish.await_args.kwargs["headers"]["attempt"] == attempt + 1


async def test_failed_retry_publish_propagates(monkeypatch):
    monkeypatch.setattr(worker, "process_payment", AsyncMock(side_effect=RuntimeError()))
    monkeypatch.setattr(worker, "client", object())
    monkeypatch.setattr(worker.broker, "publish", AsyncMock(side_effect=ConnectionError()))
    with pytest.raises(ConnectionError):
        await worker.consume({"payment_id": str(uuid4())}, AsyncMock(headers={}))


async def test_success_does_not_publish_retry(monkeypatch):
    monkeypatch.setattr(worker, "process_payment", AsyncMock())
    monkeypatch.setattr(worker, "client", object())
    publish = AsyncMock()
    monkeypatch.setattr(worker.broker, "publish", publish)
    await worker.consume({"payment_id": str(uuid4())}, AsyncMock(headers={}))
    publish.assert_not_awaited()


@pytest.mark.parametrize("body", [{}, {"payment_id": "invalid"}, ["unexpected"], "invalid"])
async def test_invalid_event_uses_retry_policy(monkeypatch, body):
    process = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(worker, "process_payment", process)
    monkeypatch.setattr(worker.broker, "publish", publish)
    await worker.consume(body, AsyncMock(headers={"attempt": 3}))
    process.assert_not_awaited()
    assert publish.await_args.kwargs["queue"] == dead_queue
