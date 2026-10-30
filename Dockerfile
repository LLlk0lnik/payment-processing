FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /service
COPY pyproject.toml constraints.txt ./
COPY app ./app
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10001 --create-home service
COPY alembic.ini ./
COPY migrations ./migrations
USER service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
