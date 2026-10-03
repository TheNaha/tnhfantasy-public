# Health API tests


def test_liveness_check(client):
    """Liveness: the process is up. It must not depend on the database.

    Renamed from `/api/health`, which was this same handler under a third name
    for the same two ideas the stack already had (`/live` on the providers,
    `/api/ready` here).
    """
    response = client.get("/api/live")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"


def test_readiness_check(client):
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_health_is_gone(client):
    """The redundant endpoint is removed, not merely renamed alongside.

    A left-behind alias is how `/api/health` outlived its usefulness in the
    first place: nothing called it, and nothing noticed it was still there.
    """
    assert client.get("/api/health").status_code == 404
