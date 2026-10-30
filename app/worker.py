import asyncio
import logging
from typing import Any

import httpx
from faststream import FastStream
from faststream.rabbit import RabbitMessage

from app.config import get_settings
from app.db import engine
from app.messaging import dead_queue, declare_queues, make_broker, queue, retry_queues
from app.schemas import PaymentEvent
from app.services.processing import process_payment

logger = logging.getLogger(__name__)
broker = make_broker()
app = FastStream(broker)
client: httpx.AsyncClient | None = None


@app.on_startup
async def startup():
    global client
    await broker.connect()
    await declare_queues(broker)
    client = httpx.AsyncClient(timeout=get_settings().webhook_timeout, follow_redirects=False)


@app.after_shutdown
async def shutdown():
    if client is not None:
        await client.aclose()
    await engine.dispose()


@broker.subscriber(queue, no_ack=False, retry=True)
async def consume(body: Any, message: RabbitMessage):
    attempt = message.headers.get("attempt", 1)
    if type(attempt) is not int or attempt < 1 or attempt > 3:
        attempt = 3
    try:
        event = PaymentEvent.model_validate(body)
        assert client is not None
        await process_payment(event.payment_id, client)
    except Exception as error:
        logger.exception("Payment delivery failed, attempt=%s", attempt)
        target = retry_queues[attempt - 1] if attempt < 3 else dead_queue
        # A failed publish propagates: the source message is requeued, never acknowledged.
        await broker.publish(
            body,
            queue=target,
            persist=True,
            mandatory=True,
            headers={"attempt": attempt + 1, "error_type": type(error).__name__},
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(app.run())
