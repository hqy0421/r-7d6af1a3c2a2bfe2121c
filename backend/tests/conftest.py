"""Test fixtures.

Checks are routed into the ASGI app itself, so the engine runs against real
HTTP responses from the bundled /demo endpoints without touching the network.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator

import pytest

TEST_DB = os.path.join(tempfile.mkdtemp(prefix="pulsewatch-tests-"), "test.db")
os.environ.update(
    ENVIRONMENT="development",
    DATABASE_URL=f"sqlite:///{TEST_DB}",
    SECRET_KEY="test-secret-not-used-anywhere-else-0123456789",
    ALLOW_REGISTRATION="true",
    # The tests drive the engine directly; a background scheduler would race
    # their assertions.
    SCHEDULER_ENABLED="false",
    DEFAULT_FAILURE_THRESHOLD="3",
    NOTIFICATIONS_DRY_RUN="true",
    PUBLIC_API_URL="http://localhost:8000",
)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.http_client import set_transport, stop_client  # noqa: E402

PASSWORD = "correct-horse-battery"
DEMO_BASE = "http://localhost:8000"


@pytest.fixture(autouse=True)
async def fresh_state() -> Iterator[None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    reset_rate_limits()
    # Every check in the suite is served by the app under test.
    await stop_client()
    set_transport(httpx.ASGITransport(app=app))
    yield
    await stop_client()
    set_transport(None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, base_url=DEMO_BASE) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    response = client.post(
        "/api/auth/register", json={"email": "dev@example.com", "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    return client


@pytest.fixture
def make_monitor(auth_client: TestClient) -> Callable[..., dict]:
    def factory(path: str = "/demo/healthy", **overrides) -> dict:
        body = {
            "name": overrides.pop("name", "Demo monitor"),
            "url": f"{DEMO_BASE}{path}",
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "expected_status": 200,
        }
        body.update(overrides)
        response = auth_client.post("/api/monitors", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return factory
