from faststream.rabbit import RabbitBroker, RabbitQueue

QUEUE_NAME = "payments.new"
DLQ_NAME = "payments.dead"
RETRY_DELAYS = (1000, 2000)


queue = RabbitQueue(
    QUEUE_NAME,
    durable=True,
    arguments={"x-dead-letter-exchange": "", "x-dead-letter-routing-key": DLQ_NAME},
)
dead_queue = RabbitQueue(DLQ_NAME, durable=True)
retry_queues = [
    RabbitQueue(
        f"{QUEUE_NAME}.retry.{index}",
        durable=True,
        arguments={
            "x-message-ttl": delay,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": QUEUE_NAME,
            "x-queue-type": "quorum",
            "x-dead-letter-strategy": "at-least-once",
            "x-overflow": "reject-publish",
        },
    )
    for index, delay in enumerate(RETRY_DELAYS, start=1)
]


async def declare_queues(broker: RabbitBroker) -> None:
    await broker.declare_queue(dead_queue)
    await broker.declare_queue(queue)
    for retry_queue in retry_queues:
        await broker.declare_queue(retry_queue)
