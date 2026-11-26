"""The check engine and the incident state machine."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.models.monitor_check import CheckOutcome
from app.services.checker import CheckTarget, run_check
from app.services.http_client import set_transport
from tests.conftest import DEMO_BASE


async def test_a_healthy_endpoint_is_up() -> None:
    result = await run_check(CheckTarget(url=f"{DEMO_BASE}/demo/healthy"))
    assert result.outcome == CheckOutcome.UP
    assert result.status_code == 200
    assert result.response_ms is not None and result.response_ms >= 0
    assert result.error is None


async def test_a_slow_endpoint_is_degraded_not_down() -> None:
    result = await run_check(
        CheckTarget(url=f"{DEMO_BASE}/demo/slow?seconds=0.3", degraded_ms=50)
    )
    assert result.outcome == CheckOutcome.DEGRADED
    assert result.status_code == 200


async def test_an_unexpected_status_is_down_with_a_reason() -> None:
    result = await run_check(CheckTarget(url=f"{DEMO_BASE}/demo/error"))
    assert result.outcome == CheckOutcome.DOWN
    assert result.status_code == 500
    assert "Expected 200, got 500" in (result.error or "")


async def test_a_timeout_is_reported_as_a_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    set_transport(httpx.MockTransport(handler))
    from app.services.http_client import stop_client

    await stop_client()  # rebuild the client on the mock transport
    result = await run_check(CheckTarget(url="https://example.com/health", timeout_seconds=1))
    assert result.outcome == CheckOutcome.DOWN
    assert "Timeout" in (result.error or "")


async def test_a_private_target_is_refused_before_any_request() -> None:
    """The SSRF guard runs inside the engine, not only at save time."""
    result = await run_check(CheckTarget(url="http://169.254.169.254/latest/meta-data/"))
    assert result.outcome == CheckOutcome.DOWN
    assert "private address" in (result.error or "")


@pytest.mark.parametrize("threshold", [1, 3])
def test_incidents_open_only_after_the_threshold(
    auth_client: TestClient, make_monitor, threshold: int
) -> None:
    monitor = make_monitor("/demo/error", failure_threshold=threshold, name=f"t{threshold}")
    monitor_id = monitor["id"]

    for attempt in range(1, threshold + 1):
        auth_client.post(f"/api/monitors/{monitor_id}/check")
        state = auth_client.get(f"/api/monitors/{monitor_id}").json()
        incidents = auth_client.get(f"/api/monitors/{monitor_id}/incidents").json()
        if attempt < threshold:
            # Failing, but not yet an outage: this is what stops a single
            # dropped packet from paging anyone.
            assert state["status"] == "degraded"
            assert incidents["total"] == 0
        else:
            assert state["status"] == "down"
            assert incidents["total"] == 1


def test_repeated_failures_extend_one_incident(auth_client: TestClient, make_monitor) -> None:
    monitor = make_monitor("/demo/error", failure_threshold=2)
    for _ in range(5):
        auth_client.post(f"/api/monitors/{monitor['id']}/check")

    incidents = auth_client.get(f"/api/monitors/{monitor['id']}/incidents").json()
    assert incidents["total"] == 1
    incident = incidents["items"][0]
    assert incident["status"] == "open"
    assert incident["failure_count"] == 5
    kinds = [entry["kind"] for entry in incident["timeline"]]
    assert kinds[0] == "detected"
    assert kinds.count("failing") >= 3


def test_recovery_resolves_the_incident_and_records_downtime(
    auth_client: TestClient, make_monitor
) -> None:
    monitor = make_monitor("/demo/error", failure_threshold=1)
    auth_client.post(f"/api/monitors/{monitor['id']}/check")
    assert auth_client.get(f"/api/monitors/{monitor['id']}").json()["status"] == "down"

    # Point the same monitor at a healthy endpoint and check again.
    auth_client.patch(f"/api/monitors/{monitor['id']}", json={"url": f"{DEMO_BASE}/demo/healthy"})
    auth_client.post(f"/api/monitors/{monitor['id']}/check")

    state = auth_client.get(f"/api/monitors/{monitor['id']}").json()
    assert state["status"] == "operational"
    assert state["consecutive_failures"] == 0

    incident = auth_client.get(f"/api/monitors/{monitor['id']}/incidents").json()["items"][0]
    assert incident["status"] == "resolved"
    assert incident["resolved_at"] is not None
    assert incident["duration_seconds"] is not None
    assert incident["timeline"][-1]["kind"] in ("resolved", "notified")


def test_a_success_resets_the_failure_counter(auth_client: TestClient, make_monitor) -> None:
    monitor = make_monitor("/demo/error", failure_threshold=3)
    auth_client.post(f"/api/monitors/{monitor['id']}/check")
    assert auth_client.get(f"/api/monitors/{monitor['id']}").json()["consecutive_failures"] == 1

    auth_client.patch(f"/api/monitors/{monitor['id']}", json={"url": f"{DEMO_BASE}/demo/healthy"})
    auth_client.post(f"/api/monitors/{monitor['id']}/check")
    assert auth_client.get(f"/api/monitors/{monitor['id']}").json()["consecutive_failures"] == 0
