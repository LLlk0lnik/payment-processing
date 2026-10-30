import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from app.core.config import get_settings


async def authenticate(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().api_key.get_secret_value()
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key")
