"""Run against Docker Desktop: python tests/smoke.py (requires the compose stack)."""

import json
import os
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx

received = defaultdict(list)


class Webhook(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        received[payload["payment_id"]].append((time.monotonic(), payload, self.headers))
        self.send_response(503 if self.path == "/fail" else 204)
        self.end_headers()

    def log_message(self, *args):
        pass


def wait_until(predicate, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise AssertionError("Timed out waiting for the expected delivery")


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 19090), Webhook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    headers = {"X-API-Key": os.getenv("API_KEY", "local-development-key")}
    try:
        with httpx.Client(base_url="http://localhost:8000", headers=headers, timeout=10) as api:
            ids = []
            for path in ("/success", "/fail"):
                request_headers = {"Idempotency-Key": f"smoke-{uuid4()}"}
                body = {
                    "amount": "123.45",
                    "currency": "RUB",
                    "description": "Smoke test",
                    "metadata": {"test": True},
                    "webhook_url": f"http://host.docker.internal:19090{path}",
                }
                response = api.post("/api/v1/payments", headers=request_headers, json=body)
                assert response.status_code == 202, response.text
                payment_id = response.json()["payment_id"]
                duplicate = api.post("/api/v1/payments", headers=request_headers, json=body)
                assert duplicate.json()["payment_id"] == payment_id
                ids.append(payment_id)
            success_id, failed_hook_id = ids
            wait_until(
                lambda: len(received[success_id]) == 1 and len(received[failed_hook_id]) == 3
            )
            attempts = received[failed_hook_id]
            assert attempts[1][0] - attempts[0][0] >= 0.9
            assert attempts[2][0] - attempts[1][0] >= 1.9
            assert len({json.dumps(item[1], sort_keys=True) for item in attempts}) == 1
            for payment_id in ids:
                detail = api.get(f"/api/v1/payments/{payment_id}").json()
                assert detail["status"] in {"succeeded", "failed"}
                assert detail["processed_at"] is not None
                for _, payload, delivery_headers in received[payment_id]:
                    assert payload["status"] == detail["status"]
                    assert delivery_headers["Idempotency-Key"] == payment_id
        with httpx.Client(base_url="http://localhost:15672", auth=("payments", "payments")) as rmq:

            def in_dlq():
                result = rmq.post(
                    "/api/queues/%2F/payments.dead/get",
                    json={"count": 100, "ackmode": "ack_requeue_true", "encoding": "auto"},
                )
                result.raise_for_status()
                return any(
                    json.loads(item["payload"])["payment_id"] == failed_hook_id
                    for item in result.json()
                )

            wait_until(in_dlq)
        print("PASS: API, idempotency, webhook, 1s/2s retry, three attempts, DLQ")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
