from faststream.rabbit import Channel, RabbitBroker

from app.core.config import get_settings


def make_broker() -> RabbitBroker:
    return RabbitBroker(
        get_settings().rabbitmq_url,
        default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
    )
