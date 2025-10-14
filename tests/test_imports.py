# tests/test_endpoints.py
import importlib
from fastapi.testclient import TestClient

def _build_app():
    # טוען את app מ-main (כפי שהוא כולל include_router)
    main = importlib.import_module("main")
    return main.app

def test_health_root_and_meta():
    app = _build_app()
    c = TestClient(app)
    assert c.get("/health").status_code == 200
    assert c.get("/").status_code in (200, 204)
    assert c.get("/meta/version").status_code == 200

def test_public_endpoints_ok():
    app = _build_app()
    c = TestClient(app)
    r1 = c.get("/scan/public-now")
    assert r1.status_code == 200
    assert r1.json().get("ok") is True
    r2 = c.get("/scan/public-topk?k=3")
    assert r2.status_code == 200
    assert r2.json().get("ok") is True

def test_aliases_crud_ok():
    app = _build_app()
    c = TestClient(app)
    # set
    r = c.post("/aliases/set", json={"alias": "doc", "target": "/docs"})
    assert r.status_code == 200
    # resolve
    r = c.get("/aliases/resolve", params={"alias": "doc"})
    assert r.status_code == 200
    assert r.json()["target"] == "/docs"
    # delete
    r = c.delete("/aliases/delete", params={"alias": "doc"})
    assert r.status_code == 200
    # resolve missing
    r = c.get("/aliases/resolve", params={"alias": "doc"})
    assert r.status_code == 404
