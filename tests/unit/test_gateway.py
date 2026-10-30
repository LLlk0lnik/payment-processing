from unittest.mock import AsyncMock, Mock

import pytest

from app.services import gateway


@pytest.mark.parametrize(
    "draw,expected",
    [(0.0, "succeeded"), (0.899999, "succeeded"), (0.9, "failed"), (0.999999, "failed")],
)
async def test_gateway_delay_and_probability_boundary(monkeypatch, draw, expected):
    delay = Mock(return_value=3.5)
    sleep = AsyncMock()
    monkeypatch.setattr(gateway.random, "uniform", delay)
    monkeypatch.setattr(gateway.random, "random", Mock(return_value=draw))
    monkeypatch.setattr(gateway.asyncio, "sleep", sleep)

    assert await gateway.emulate_gateway() == expected
    delay.assert_called_once_with(2, 5)
    sleep.assert_awaited_once_with(3.5)
