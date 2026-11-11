from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_open():
    assert client.get("/health").json() == {"ok": True}


def test_requires_api_key():
    assert client.post("/sql", json={"question": "hello there"}).status_code == 401


def test_visual_rejects_row_data():
    r = client.post("/visual", headers={"X-API-Key": "change-me"},
                    json={"question": "chart it", "columns": [{"name": "A"}], "rows": [{"A": 1}]})
    assert r.status_code == 422
