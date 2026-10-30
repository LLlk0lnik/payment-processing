from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.payments import router
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="Payment Processing", version="1.0.0", lifespan=lifespan)
app.include_router(router)
