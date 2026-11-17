"""Static frontend serving: app shell, SPA fallback, cache headers, API paths untouched."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.static import install_static


def make_app(tmp_path, with_index=True) -> FastAPI:
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    if with_index:
        (root / "index.html").write_text("<!doctype html><title>Stacklight</title><div id=root></div>")
    (root / "assets" / "app-abc123.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the static root")
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/ping")
    def ping():
        return {"pong": True}

    install_static(app, root)
    return app


def test_root_serves_the_app_shell_uncached(tmp_path):
    c = TestClient(make_app(tmp_path))
    r = c.get("/")
    assert r.status_code == 200 and "<div id=root>" in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-type"].startswith("text/html")


def test_spa_routes_fall_back_to_index(tmp_path):
    c = TestClient(make_app(tmp_path))
    r = c.get("/some/client/route")
    assert r.status_code == 200 and "<div id=root>" in r.text


def test_hashed_assets_get_a_long_immutable_cache(tmp_path):
    c = TestClient(make_app(tmp_path))
    r = c.get("/assets/app-abc123.js")
    assert r.status_code == 200 and r.text == "console.log(1)"
    assert "immutable" in r.headers["cache-control"] and "max-age=31536000" in r.headers["cache-control"]
    assert "immutable" not in c.get("/favicon.svg").headers["cache-control"]


def test_missing_files_are_404_not_the_app_shell(tmp_path):
    c = TestClient(make_app(tmp_path))
    assert c.get("/assets/missing.js").status_code == 404
    assert c.get("/nope.css").status_code == 404


def test_unknown_api_paths_stay_json_404(tmp_path):
    c = TestClient(make_app(tmp_path))
    r = c.get("/api/does-not-exist")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": "Not Found"}
    assert c.get("/api").status_code == 404
    assert c.get("/api/ping").json() == {"pong": True}
    assert c.get("/health").json() == {"status": "ok"}


def test_path_traversal_cannot_leave_the_static_root(tmp_path):
    c = TestClient(make_app(tmp_path))
    for p in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        r = c.get(p)
        assert "outside the static root" not in r.text


def test_no_static_dir_means_nothing_is_mounted(tmp_path):
    app = make_app(tmp_path, with_index=False)
    c = TestClient(app)
    assert c.get("/").status_code == 404
    assert c.get("/health").status_code == 200


def test_real_app_starts_without_a_static_dir():
    from app.api.main import app

    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_nul_and_oversized_paths_are_404_not_500(tmp_path):
    c = TestClient(make_app(tmp_path), raise_server_exceptions=False)
    assert c.get("/assets/a%00b.js").status_code == 404
    assert c.get("/%00").status_code == 404
    assert c.get("/" + "a" * 5000 + ".js").status_code == 404
