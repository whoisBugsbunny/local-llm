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


def test_chat_includes_execution_time(monkeypatch):
    from types import SimpleNamespace

    import app.main as main

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(service_api_key="test-key"))
    monkeypatch.setattr(main, "get_provider", lambda *_: SimpleNamespace(name="fake", model="fake-1"))
    monkeypatch.setattr(main, "default_store", lambda: object())
    monkeypatch.setattr(main.service, "chat", lambda *args: "Hello")

    response = client.post(
        "/chat",
        headers={"X-API-Key": "test-key"},
        json={"messages": [{"role": "user", "content": "Hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "Hello"
    assert isinstance(response.json()["execution_time_ms"], (int, float))
    assert response.json()["execution_time_ms"] >= 0
