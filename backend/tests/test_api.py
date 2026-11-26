"""Authentication, ownership, monitors, channels and the public status page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DEMO_BASE, PASSWORD

PROTECTED = ["/api/auth/me", "/api/monitors", "/api/incidents", "/api/dashboard", "/api/channels"]


@pytest.mark.parametrize("path", PROTECTED)
def test_management_routes_require_a_session(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_register_and_login(client: TestClient) -> None:
    created = client.post(
        "/api/auth/register", json={"email": " Dev@Example.COM ", "password": PASSWORD}
    )
    assert created.status_code == 201
    assert created.json()["email"] == "dev@example.com"
    assert "HttpOnly" in created.headers["set-cookie"]

    wrong = client.post("/api/auth/login", json={"email": "dev@example.com", "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": "who@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_monitors_are_scoped_to_their_owner(auth_client: TestClient, make_monitor) -> None:
    monitor = make_monitor()
    auth_client.post("/api/auth/logout")
    auth_client.cookies.clear()
    auth_client.post("/api/auth/register", json={"email": "other@example.com", "password": PASSWORD})

    # 404, not 403: the API does not confirm that the id exists.
    assert auth_client.get(f"/api/monitors/{monitor['id']}").status_code == 404
    assert auth_client.patch(f"/api/monitors/{monitor['id']}", json={"name": "x"}).status_code == 404
    assert auth_client.delete(f"/api/monitors/{monitor['id']}").status_code == 404
    assert auth_client.post(f"/api/monitors/{monitor['id']}/check").status_code == 404
    assert auth_client.get("/api/monitors").json() == []


def test_a_private_url_is_refused_at_save_time(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/monitors",
        json={"name": "Internal", "url": "http://127.0.0.1:5432/", "interval_seconds": 60},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsafe_target"


def test_forbidden_headers_are_rejected(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/monitors",
        json={
            "name": "Bad headers",
            "url": f"{DEMO_BASE}/demo/healthy",
            "headers": {"Host": "example.com"},
        },
    )
    assert response.status_code == 422


def test_run_check_now_returns_a_real_result(auth_client: TestClient, make_monitor) -> None:
    monitor = make_monitor("/demo/healthy")
    response = auth_client.post(f"/api/monitors/{monitor['id']}/check")
    assert response.status_code == 200

    body = response.json()
    assert body["outcome"] == "up"
    assert body["status_code"] == 200
    assert body["response_ms"] is not None
    assert body["monitor_status"] == "operational"

    history = auth_client.get(f"/api/monitors/{monitor['id']}/checks").json()
    assert history["total"] == 1
    assert history["items"][0]["manual"] is True


def test_uptime_is_computed_from_checks_and_reports_its_window(
    auth_client: TestClient, make_monitor
) -> None:
    monitor = make_monitor("/demo/healthy")
    for _ in range(3):
        auth_client.post(f"/api/monitors/{monitor['id']}/check")
    auth_client.patch(f"/api/monitors/{monitor['id']}", json={"url": f"{DEMO_BASE}/demo/error"})
    auth_client.post(f"/api/monitors/{monitor['id']}/check")

    detail = auth_client.get(f"/api/monitors/{monitor['id']}").json()
    assert detail["uptime"]["24h"]["checks"] == 4
    assert detail["uptime"]["24h"]["uptime"] == 75.0
    # Four checks in a minute do not cover thirty days, and the API says so.
    assert detail["uptime"]["30d"]["partial"] is True
    assert len(detail["sparkline"]) == 4


def test_pausing_a_monitor_stops_it_being_scheduled(
    auth_client: TestClient, make_monitor
) -> None:
    monitor = make_monitor()
    paused = auth_client.patch(f"/api/monitors/{monitor['id']}", json={"enabled": False}).json()
    assert paused["enabled"] is False
    assert paused["status"] == "paused"

    from app.services.scheduler import scheduler

    claimed = scheduler._claim_due()  # noqa: SLF001 - exercising the claim directly
    assert all(item.id != monitor["id"] for item in claimed)


def test_channel_credentials_are_masked_and_encrypted(auth_client: TestClient) -> None:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import NotificationChannel

    url = "https://discord.com/api/webhooks/123456/super-secret-token"
    created = auth_client.post(
        "/api/channels",
        json={"name": "Ops", "type": "discord", "config": {"webhook_url": url}},
    )
    assert created.status_code == 201
    assert "super-secret-token" not in created.text
    assert created.json()["config"]["webhook_url"].startswith("••••••")

    with SessionLocal() as db:
        stored = db.execute(select(NotificationChannel)).scalar_one()
    assert "super-secret-token" not in str(stored.config)
    assert "__enc__" in stored.config["webhook_url"]


def test_alerts_are_rendered_for_down_and_recovery() -> None:
    from app.models import Incident, IncidentStatus, Monitor
    from app.services.notifications import build_alert

    monitor = Monitor(id=1, user_id=1, name="Production API", url="https://example.com/health")
    incident = Incident(
        id=1, monitor_id=1, user_id=1, status=IncidentStatus.OPEN,
        reason="Timeout after 10s", failure_count=3,
    )
    down = build_alert(monitor, incident, recovered=False)
    assert "🔴" in down.title and "DOWN" in down.title
    assert "Timeout after 10s" in down.body
    assert down.payload["event"] == "monitor.down"

    incident.duration_seconds = 194
    recovered = build_alert(monitor, incident, recovered=True)
    assert "🟢" in recovered.title
    assert "3m 14s" in recovered.body


def test_the_public_status_page_needs_no_session_and_leaks_nothing(
    auth_client: TestClient, make_monitor, client: TestClient
) -> None:
    healthy = make_monitor("/demo/healthy", name="API")
    broken = make_monitor("/demo/error", name="Checkout", failure_threshold=1)
    auth_client.post(f"/api/monitors/{healthy['id']}/check")
    auth_client.post(f"/api/monitors/{broken['id']}/check")

    page = auth_client.post(
        "/api/status-pages",
        json={
            "slug": "acme",
            "title": "Acme Platform",
            "monitor_ids": [healthy["id"], broken["id"]],
        },
    )
    assert page.status_code == 201

    auth_client.cookies.clear()  # a visitor has no session
    public = auth_client.get("/api/status/acme")
    assert public.status_code == 200

    body = public.json()
    assert body["title"] == "Acme Platform"
    assert body["overall"] == "major_outage"
    assert [service["name"] for service in body["services"]] == ["API", "Checkout"]
    assert body["incidents"][0]["service"] == "Checkout"
    # No URLs, no configuration, no owner.
    assert "demo/healthy" not in public.text
    assert "url" not in body["services"][0]


def test_an_unpublished_status_page_is_not_served(auth_client: TestClient, make_monitor) -> None:
    make_monitor()
    auth_client.post(
        "/api/status-pages",
        json={"slug": "private", "title": "Internal", "monitor_ids": [], "published": False},
    )
    auth_client.cookies.clear()
    assert auth_client.get("/api/status/private").status_code == 404


def test_the_dashboard_counts_match_the_monitors(auth_client: TestClient, make_monitor) -> None:
    healthy = make_monitor("/demo/healthy", name="A")
    broken = make_monitor("/demo/error", name="B", failure_threshold=1)
    auth_client.post(f"/api/monitors/{healthy['id']}/check")
    auth_client.post(f"/api/monitors/{broken['id']}/check")

    dashboard = auth_client.get("/api/dashboard").json()
    assert dashboard["monitors"] == 2
    assert dashboard["operational"] == 1
    assert dashboard["down"] == 1
    assert dashboard["open_incidents"] == 1
    assert dashboard["checks_24h"] == 2
    assert dashboard["uptime_24h"] == 50.0


def test_failed_checks_appear_as_gaps_in_the_sparkline(
    auth_client: TestClient, make_monitor
) -> None:
    """A fast 500 still has a latency, but the card must not draw it as healthy."""
    monitor = make_monitor("/demo/healthy")
    auth_client.post(f"/api/monitors/{monitor['id']}/check")
    auth_client.patch(f"/api/monitors/{monitor['id']}", json={"url": f"{DEMO_BASE}/demo/error"})
    auth_client.post(f"/api/monitors/{monitor['id']}/check")

    sparkline = auth_client.get(f"/api/monitors/{monitor['id']}").json()["sparkline"]
    assert sparkline[0] is not None
    assert sparkline[1] is None
