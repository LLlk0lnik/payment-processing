import os

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://payments:payments@localhost/payments")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost/")
