from unittest.mock import AsyncMock, Mock

import pytest

from app.services import processing


@pytest.mark.parametrize(
    "draw,expected",
    [(0.0, "succeeded"), (0.899999, "succeeded"), (0.9, "failed"), (0.999999, "failed")],
)
async def test_gateway_delay_and_probability_boundary(monkeypatch, draw, expected):
    delay = Mock(return_value=3.5)
    sleep = AsyncMock()
    monkeypatch.setattr(processing.random, "uniform", delay)
    monkeypatch.setattr(processing.random, "random", Mock(return_value=draw))
    monkeypatch.setattr(processing.asyncio, "sleep", sleep)

    assert await processing.emulate_gateway() == expected
    delay.assert_called_once_with(2, 5)
    sleep.assert_awaited_once_with(3.5)
