from uuid import UUID

from pydantic import BaseModel


class PaymentEvent(BaseModel):
    payment_id: UUID
