"""Pruebas de integración de la API + cola + renderizado real (IA sustituida por doble de prueba)."""

from __future__ import annotations

import io
import time

from conftest import TOKEN, PermanentAIError, TransientAIError, jpeg_bytes
from PIL import Image

from app import db as dbm
from app.ai import Analysis, Visual


def post_job(client, cid="job-0001-abcd", n=1, consent="true", **extra):
    files = [("files", (f"p{i}.jpg", jpeg_bytes(color=(255, 255 - i, 255)), "image/jpeg")) for i in range(n)]
    data = {"client_job_id": cid, "consent": consent, **extra}
    return client.post("/v1/jobs", files=files, data=data)


def run_worker(app) -> bool:
    return app.state.worker.run_once()


# ------------------------------------------------------------------ auth
def test_health_is_public(client):
    r = client.get("/health", headers={"Authorization": ""})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["ai_configured"] is False  # sin clave en los tests


def test_requires_token(client):
    r = client.get("/v1/me", headers={"Authorization": ""})
    assert r.status_code == 401
    r = client.get("/v1/me", headers={"Authorization": "Bearer otro"})
    assert r.status_code == 401
    assert client.get("/v1/me").status_code == 200


def test_https_required(settings, fake_ai):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings.require_https = True
    app = create_app(settings, ai_factory=lambda: fake_ai, start_worker=False)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 403
        assert c.get("/health", headers={"X-Forwarded-Proto": "https"}).status_code == 200


# ---------------------------------------------------------- validaciones
def test_consent_required(client):
    r = post_job(client, consent="false")
    assert r.status_code == 400
    assert "consentimiento" in r.json()["detail"]


def test_rejects_non_image(client):
    files = [("files", ("x.jpg", b"not an image at all", "image/jpeg"))]
    r = client.post("/v1/jobs", files=files, data={"client_job_id": "job-bad-0001", "consent": "true"})
    assert r.status_code == 400


def test_rejects_too_many_images(client):
    r = post_job(client, n=5)
    assert r.status_code == 400


def test_invalid_preset_and_client_id(client):
    assert post_job(client, preset="tv").status_code == 400
    assert post_job(client, cid="bad id!").status_code == 400


# ------------------------------------------------------- idempotencia
def test_duplicate_client_job_id_returns_same_job(client):
    a = post_job(client, cid="same-id-0001")
    b = post_job(client, cid="same-id-0001")
    assert a.status_code == 202 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    assert b.json()["duplicate"] is True


def test_duplicate_images_detected(client):
    a = post_job(client, cid="img-dup-0001")
    b = post_job(client, cid="img-dup-0002")  # mismas imágenes, otro id
    assert b.status_code == 200
    assert b.json()["id"] == a.json()["id"]


def test_daily_limits(client):
    for i in range(4):
        files = [("files", ("p.jpg", jpeg_bytes(color=(i * 40, 10, 10)), "image/jpeg")) for _ in range(2)]
        r = client.post("/v1/jobs", files=files, data={"client_job_id": f"limit-{i:04d}", "consent": "true"})
        assert r.status_code == 202, r.text
    # 8 imágenes usadas: la siguiente supera max_images_per_day
    files = [("files", ("p.jpg", jpeg_bytes(color=(1, 99, 1)), "image/jpeg"))]
    r = client.post("/v1/jobs", files=files, data={"client_job_id": "limit-9999", "consent": "true"})
    assert r.status_code == 429


# ----------------------------------------------------- flujo completo
def test_full_flow_process_download_ack(app, client, fake_ai, settings):
    r = post_job(client, n=2, cid="flow-0001")
    assert r.status_code == 202
    job_id = r.json()["id"]
    assert r.json()["status"] == "queued"

    assert run_worker(app) is True
    job = client.get(f"/v1/jobs/{job_id}").json()
    assert job["status"] == "completed", job
    assert fake_ai.calls == 1
    names = [f["name"] for f in job["files"]]
    assert names[0].startswith("01-respuesta-1de")
    assert any("imagen" in n for n in names)

    # fotos temporales eliminadas tras procesar (por defecto)
    assert app.state.storage.list_uploads(job_id) == []

    for f in job["files"]:
        d = client.get(f["url"])
        assert d.status_code == 200
        assert d.headers["content-type"] == "image/png"
        img = Image.open(io.BytesIO(d.content))
        assert img.size == (396 * 2, 484 * 2)  # preset watch

    res = client.get(f"/v1/jobs/{job_id}/result").json()
    assert "Ejercicio 1" in res["result"]["markdown"]

    # ack incompleto -> 400; completo -> acknowledged
    assert client.post(f"/v1/jobs/{job_id}/ack", json={"saved": names[:1]}).status_code == (400 if len(names) > 1 else 200)
    ok = client.post(f"/v1/jobs/{job_id}/ack", json={"saved": names})
    assert ok.status_code == 200
    assert ok.json()["status"] == "acknowledged"
    # ack repetido es idempotente
    assert client.post(f"/v1/jobs/{job_id}/ack", json={"saved": names}).status_code == 200


def test_phone_preset_size(app, client):
    r = post_job(client, cid="phone-0001", preset="phone")
    run_worker(app)
    job = client.get(f"/v1/jobs/{r.json()['id']}").json()
    d = client.get(job["files"][0]["url"])
    assert Image.open(io.BytesIO(d.content)).size == (430 * 3, 932 * 3)


def test_list_pending_jobs(app, client):
    r = post_job(client, cid="list-0001")
    run_worker(app)
    jobs = client.get("/v1/jobs", params={"status": "completed"}).json()["jobs"]
    assert [j["id"] for j in jobs] == [r.json()["id"]]
    assert client.get("/v1/jobs", params={"status": "nope"}).status_code == 400


def test_irrelevant_photo_completes_without_files(app, client, fake_ai):
    fake_ai.analysis = Analysis(is_relevant=False, title="Foto personal", answer_markdown="", irrelevant_reason="selfie")
    r = post_job(client, cid="irrel-0001")
    run_worker(app)
    job = client.get(f"/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed"
    assert job["relevant"] is False
    assert job["files"] == []
    assert client.post(f"/v1/jobs/{job['id']}/ack", json={"saved": []}).status_code == 200


# --------------------------------------------------------- reintentos
def test_transient_error_is_retried(app, client, fake_ai):
    fake_ai.errors = [TransientAIError("rate limit")]
    r = post_job(client, cid="retry-0001")
    job_id = r.json()["id"]
    run_worker(app)
    job = client.get(f"/v1/jobs/{job_id}").json()
    assert job["status"] == "queued"
    assert "rate limit" in job["last_error"]
    assert job["attempts"] == 1
    run_worker(app)
    assert client.get(f"/v1/jobs/{job_id}").json()["status"] == "completed"


def test_attempts_exhausted_then_manual_retry(app, client, fake_ai):
    fake_ai.errors = [TransientAIError("boom")] * 3
    r = post_job(client, cid="exhaust-0001")
    job_id = r.json()["id"]
    for _ in range(3):
        run_worker(app)
    job = client.get(f"/v1/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "Agotados" in job["last_error"]
    # Las fotos se conservan para poder reintentar
    assert app.state.storage.list_uploads(job_id)
    assert client.post(f"/v1/jobs/{job_id}/retry").status_code == 200
    run_worker(app)
    assert client.get(f"/v1/jobs/{job_id}").json()["status"] == "completed"


def test_permanent_error_fails_immediately(app, client, fake_ai):
    fake_ai.errors = [PermanentAIError("modelo no existe")]
    r = post_job(client, cid="perm-0001")
    run_worker(app)
    job = client.get(f"/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed"
    assert job["attempts"] == 1


def test_analysis_cached_when_render_fails(app, client, fake_ai, monkeypatch):
    """Si el render falla tras pagar la llamada a OpenAI, el reintento no repite la llamada."""
    calls = {"n": 0}
    real = app.state.processor.renderer.render_answer

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("chromium crashed")
        return real(*a, **k)

    monkeypatch.setattr(app.state.processor.renderer, "render_answer", flaky)
    r = post_job(client, cid="cache-0001")
    run_worker(app)
    assert client.get(f"/v1/jobs/{r.json()['id']}").json()["status"] == "queued"
    run_worker(app)
    assert client.get(f"/v1/jobs/{r.json()['id']}").json()["status"] == "completed"
    assert fake_ai.calls == 1


def test_stale_processing_job_is_recovered(app, client):
    r = post_job(client, cid="stale-0001")
    job = app.state.db.claim_next()
    assert job.status == dbm.PROCESSING
    # simulamos caída del proceso: heartbeat antiguo
    with app.state.db.tx() as conn:
        conn.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (time.time() - 10_000, job.id))
    assert app.state.db.requeue_stale(900) == 1
    run_worker(app)
    assert client.get(f"/v1/jobs/{r.json()['id']}").json()["status"] == "completed"


# ----------------------------------------------------------- visuales
def test_visual_failure_is_reported_not_fatal(app, client, fake_ai):
    fake_ai.analysis = Analysis(
        is_relevant=True,
        title="Con visual roto",
        answer_markdown="Texto",
        visuals=[Visual(kind="graphviz", title="Malo", code='digraph { a [image="/etc/passwd"] }')],
    )
    r = post_job(client, cid="badvis-0001")
    run_worker(app)
    job_id = r.json()["id"]
    res = client.get(f"/v1/jobs/{job_id}/result").json()
    assert res["job"]["status"] == "completed"
    assert any("Malo" in w for w in res["result"]["warnings"])
    assert all(f["kind"] == "answer_page" for f in res["job"]["files"])


def test_illustrations_respect_option_and_limit(app, client, fake_ai, settings):
    fake_ai.analysis = Analysis(
        is_relevant=True,
        title="Diseños",
        answer_markdown="Diseños solicitados",
        visuals=[Visual(kind="illustration", title=f"Diseño {i}", prompt="logo") for i in range(3)],
    )
    r = post_job(client, cid="illus-0001", allow_illustrations="false")
    run_worker(app)
    assert fake_ai.image_calls == 0
    assert r.status_code == 202
    # imágenes distintas para evitar la deduplicación
    files = [("files", ("q.jpg", jpeg_bytes(color=(9, 9, 200)), "image/jpeg"))]
    r3 = client.post("/v1/jobs", files=files, data={"client_job_id": "illus-0003", "consent": "true"})
    run_worker(app)
    assert fake_ai.image_calls == settings.max_generated_images_per_job
    job = client.get(f"/v1/jobs/{r3.json()['id']}").json()
    assert sum(1 for f in job["files"] if f["kind"] == "visual") == settings.max_generated_images_per_job


# ------------------------------------------------------------- archivos
def test_file_access_is_scoped(app, client):
    r = post_job(client, cid="scope-0001")
    run_worker(app)
    job_id = r.json()["id"]
    assert client.get(f"/v1/jobs/{job_id}/files/..%2F..%2Fautogpt_watch.sqlite3").status_code == 404
    assert client.get(f"/v1/jobs/{job_id}/files/no-existe.png").status_code == 404
    assert client.get("/v1/jobs/otro-id").status_code == 404


def test_expired_results_are_deleted(app, client, settings):
    r = post_job(client, cid="exp-0001")
    run_worker(app)
    job_id = r.json()["id"]
    names = [f["name"] for f in client.get(f"/v1/jobs/{job_id}").json()["files"]]
    client.post(f"/v1/jobs/{job_id}/ack", json={"saved": names})
    settings.result_retention_hours_after_ack = 0
    app.state.processor.maintenance()
    assert client.get(f"/v1/jobs/{job_id}").json()["status"] == "expired"
    assert not app.state.storage.result_dir(job_id).exists()


# ------------------------------------------------------- selftest / devices
def test_selftest_job(app, client):
    r = client.post("/v1/selftest")
    assert r.status_code == 202
    run_worker(app)
    job = client.get(f"/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed"
    assert job["title"].startswith("PRUEBA")
    assert len(job["files"]) >= 2


def test_device_registration(client, app):
    assert client.post("/v1/devices", json={"apns_token": "zz"}).status_code == 400
    tok = "ab" * 32
    r = client.post("/v1/devices", json={"apns_token": tok, "environment": "sandbox"})
    assert r.status_code == 200
    owner = client.get("/v1/me").json()["owner"]
    assert app.state.db.devices_for(owner) == [(tok, "sandbox")]


def test_token_not_leaked_in_me(client):
    body = client.get("/v1/me").text
    assert TOKEN not in body


def test_rejects_jobs_when_ai_not_configured(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings, start_worker=False)  # sin doble de prueba y sin clave
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        r = post_job(c, cid="noai-0001")
        assert r.status_code == 503
        assert "OPENAI_API_KEY" in r.json()["detail"]
        # El selftest no usa IA y sigue disponible
        st = c.post("/v1/selftest")
        assert st.status_code == 202
        assert st.json()["image_count"] == 0
