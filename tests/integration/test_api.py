import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.session import get_session
from app.main import app
from app.models import OutboxEvent, Payment


async def test_authentication_and_validation():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get(f"/api/v1/payments/{uuid4()}")).status_code == 401
        response = await client.post(
            "/api/v1/payments",
            headers={"X-API-Key": "test-key"},
            json={"amount": "10", "currency": "RUB", "webhook_url": "http://client/hook"},
        )
        assert response.status_code == 422


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL is not set")
async def test_concurrent_idempotency_and_atomic_outbox():
    # Use a dedicated database: this fixture creates and drops its own schema.
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    schema = f"test_{uuid4().hex}"
    from sqlalchemy import text

    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_async_engine(
        os.environ["TEST_DATABASE_URL"], connect_args={"server_settings": {"search_path": schema}}
    )
    sessions = async_sessionmaker(test_engine, expire_on_commit=False)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            headers = {"X-API-Key": "test-key", "Idempotency-Key": "same-key"}
            body = {"amount": "12.50", "currency": "RUB", "webhook_url": "http://client/hook"}
            results = await asyncio.gather(
                *[
                    client.post(
                        "/api/v1/payments",
                        headers=headers
                        if index % 2
                        else {key.lower(): value for key, value in headers.items()},
                        json=body,
                    )
                    for index in range(10)
                ]
            )
            assert all(result.status_code == 202 for result in results)
            ids = {result.json()["payment_id"] for result in results}
            assert len(ids) == 1
            conflict = await client.post(
                "/api/v1/payments", headers=headers, json={**body, "amount": "13"}
            )
            assert conflict.status_code == 409
            detail = await client.get(f"/api/v1/payments/{ids.pop()}", headers=headers)
            assert detail.status_code == 200
            assert detail.json()["amount"] == "12.50"
            assert detail.json()["metadata"] == {}
            assert detail.json()["idempotency_key"] == "same-key"
            assert (
                await client.get(f"/api/v1/payments/{uuid4()}", headers=headers)
            ).status_code == 404
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Payment)) == 1
            assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    finally:
        app.dependency_overrides.clear()
        await test_engine.dispose()
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


@pytest.mark.parametrize("key", [None, "", "incorrect-key"])
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_api_key_required_on_both_endpoints(key, method):
    headers = {} if key is None else {"X-API-Key": key}
    headers["Idempotency-Key"] = "unauthorized-request"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        if method == "GET":
            response = await client.get(f"/api/v1/payments/{uuid4()}", headers=headers)
        else:
            response = await client.post(
                "/api/v1/payments",
                headers=headers,
                json={"amount": "10", "currency": "RUB", "webhook_url": "http://client/hook"},
            )
    assert response.status_code == 401
