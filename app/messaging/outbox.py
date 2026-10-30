import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.session import Session, engine
from app.messaging.broker import make_broker
from app.messaging.topology import declare_queues, queue
from app.models import OutboxEvent

logger = logging.getLogger(__name__)


async def publish_batch(broker) -> int:
    async with Session() as session, session.begin():
        events = (
            (
                await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.published_at.is_(None))
                    .order_by(OutboxEvent.created_at)
                    .limit(50)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for event in events:
            await broker.publish(
                event.payload,
                queue=queue,
                persist=True,
                mandatory=True,
                message_id=str(event.id),
                headers={"attempt": 1},
            )
            event.published_at = datetime.now(UTC)
        return len(events)


async def main():
    broker = make_broker()
    try:
        async with broker:
            await declare_queues(broker)
            while True:
                try:
                    count = await publish_batch(broker)
                except Exception:
                    logger.exception("Outbox publication failed; rows remain unpublished")
                    await asyncio.sleep(2)
                else:
                    if not count:
                        await asyncio.sleep(0.5)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
