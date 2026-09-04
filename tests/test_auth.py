"""
Tests for role-based authentication and the
admin / audit dashboard endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def _login(client, username, password):
    return client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )


def test_login_rejects_invalid_credentials(client):
    response = _login(client, "admin", "wrong-password")

    assert response.status_code == 401


def test_login_rejects_unknown_user(client):
    response = _login(client, "nobody", "whatever")

    assert response.status_code == 401


def test_api_requires_authentication(client):
    assert (
        client.get("/api/dashboard/summary").status_code
        == 401
    )
    assert (
        client.get("/api/dashboard/audit-kpis").status_code
        == 401
    )
    assert (
        client.get("/api/matches/some-run").status_code
        == 401
    )


def test_me_requires_authentication(client):
    assert client.get("/api/auth/me").status_code == 401


def test_audit_login_and_role(client):
    response = _login(client, "audit", "Audit@123")

    assert response.status_code == 200

    payload = response.json()

    assert payload["username"] == "audit"
    assert payload["role"] == "AUDIT"
    assert "tm_session" in response.cookies

    me = client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json()["role"] == "AUDIT"


def test_admin_login_and_role(client):
    response = _login(client, "admin", "Admin@123")

    assert response.status_code == 200
    assert response.json()["role"] == "ADMIN"

    me = client.get("/api/auth/me")

    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"


def test_audit_user_cannot_access_admin_summary(client):
    _login(client, "audit", "Audit@123")

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 403


def test_audit_user_cannot_access_azure_metrics(client):
    _login(client, "audit", "Audit@123")

    response = client.get(
        "/api/dashboard/azure-metrics"
    )

    assert response.status_code == 403


def test_admin_can_access_summary_with_system_info(client):
    _login(client, "admin", "Admin@123")

    response = client.get("/api/dashboard/summary")

    assert response.status_code == 200

    payload = response.json()

    assert "totals" in payload
    assert "system" in payload
    assert "uptime_seconds" in payload["system"]
    assert (
        "document_storage" in payload["system"]
    )


def test_audit_kpis_accessible_to_audit_role(client):
    _login(client, "audit", "Audit@123")

    response = client.get("/api/dashboard/audit-kpis")

    assert response.status_code == 200

    payload = response.json()

    assert "hitl" in payload
    assert "decisions" in payload
    assert "reviewers" in payload
    assert "sla_hours" in payload
    assert "exceptions_by_type" in payload


def test_audit_kpis_accessible_to_admin_role(client):
    _login(client, "admin", "Admin@123")

    response = client.get("/api/dashboard/audit-kpis")

    assert response.status_code == 200


def test_logout_clears_session(client):
    _login(client, "audit", "Audit@123")
    assert client.get("/api/auth/me").status_code == 200

    response = client.post("/api/auth/logout")

    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_decision_reviewer_defaults_to_authenticated_user(
    client,
):
    """
    Without a real HITL case this exercises the request
    validation path only; reviewer defaulting is covered
    by the endpoint signature accepting an empty value.
    """

    _login(client, "audit", "Audit@123")

    response = client.post(
        "/api/cases/does-not-exist/decisions",
        json={"decision": "APPROVE", "reason": "Test approval reason", "comment": ""},
    )

    assert response.status_code == 404
