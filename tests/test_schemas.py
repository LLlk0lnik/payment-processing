from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import PaymentCreate


def request(**overrides):
    return {"amount": "100.00", "currency": "RUB", "webhook_url": "http://client/hook", **overrides}


@pytest.mark.parametrize("amount", ["0", "-1", "1.001", "NaN", "Infinity", "10000000000000000"])
def test_invalid_amount(amount):
    with pytest.raises(ValidationError):
        PaymentCreate(**request(amount=amount))


def test_money_and_canonical_fingerprint():
    first = PaymentCreate(**request(amount="10.0", metadata={"b": 2, "a": 1}))
    second = PaymentCreate(**request(amount="10.00", metadata={"a": 1, "b": 2}))
    assert first.amount == Decimal("10")
    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != PaymentCreate(**request()).fingerprint()


@pytest.mark.parametrize(
    "override", [{"currency": "GBP"}, {"webhook_url": "ftp://client"}, {"unknown": True}]
)
def test_invalid_request(override):
    with pytest.raises(ValidationError):
        PaymentCreate(**request(**override))
