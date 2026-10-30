import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Amount = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2, allow_inf_nan=False)]
Currency = Literal["RUB", "USD", "EUR"]
Status = Literal["pending", "succeeded", "failed"]


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Amount
    currency: Currency
    description: str = Field(default="", max_length=4096)
    metadata: dict = Field(default_factory=dict)
    webhook_url: HttpUrl

    def fingerprint(self) -> str:
        data = self.model_dump(mode="json")
        data["amount"] = format(self.amount.quantize(Decimal("0.01")), "f")
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


class PaymentAccepted(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID = Field(validation_alias="id")
    status: Status
    created_at: datetime


class PaymentDetail(PaymentAccepted):
    idempotency_key: str
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict = Field(validation_alias="payment_metadata")
    webhook_url: str
    processed_at: datetime | None


class PaymentEvent(BaseModel):
    payment_id: UUID
