"""API HTTP de AutoGPT Watch (FastAPI).

Endpoints (todos bajo /v1 requieren `Authorization: Bearer <token de dispositivo>`):
  POST /v1/jobs                     crear trabajo (multipart, idempotente por client_job_id)
  GET  /v1/jobs                     listar trabajos (filtro ?status=completed,failed)
  GET  /v1/jobs/{id}                estado
  GET  /v1/jobs/{id}/result         respuesta (Markdown + metadatos)
  GET  /v1/jobs/{id}/files/{name}   descargar PNG generado
  POST /v1/jobs/{id}/ack            confirmar guardado en Fotos
  POST /v1/jobs/{id}/retry          reintentar un trabajo fallido
  POST /v1/devices                  registrar token APNs
  POST /v1/selftest                 trabajo de PRUEBA de renderizado (sin IA)
  GET  /v1/me                       comprobar token y consumo
  GET  /health                      estado del servidor (sin autenticación)
"""

from __future__ import annotations

import hmac
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import db as dbm
from .ai import AIProvider, OpenAIProvider
from .config import Settings, get_settings, hash_token
from .db import Database, Job
from .push import APNsClient
from .render.renderer import Renderer
from .render.theme import PRESETS
from .storage import Storage, UploadRejected, validate_image
from .worker import JobProcessor, Worker

VERSION = "1.0.0"
CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
APNS_TOKEN = re.compile(r"^[0-9a-fA-F]{32,200}$")
DEDUPE_WINDOW_SECONDS = 7 * 24 * 3600

log = logging.getLogger("autogpt.api")


# ------------------------------------------------------------------ modelos
class FileOut(BaseModel):
    name: str
    kind: str
    index: int
    title: str
    bytes: int
    sha256: str
    url: str


class JobOut(BaseModel):
    id: str
    client_job_id: str
    status: str
    created_at: float
    updated_at: float
    attempts: int
    image_count: int
    last_error: str | None = None
    title: str | None = None
    relevant: bool | None = None
    files: list[FileOut] = Field(default_factory=list)
    completed_at: float | None = None
    acked_at: float | None = None
    duplicate: bool = False


class JobList(BaseModel):
    jobs: list[JobOut]


class AckIn(BaseModel):
    saved: list[str] = Field(default_factory=list)


class DeviceIn(BaseModel):
    apns_token: str
    environment: str = "production"


def job_out(job: Job, duplicate: bool = False) -> JobOut:
    files = []
    if job.status in (dbm.COMPLETED, dbm.ACKNOWLEDGED):
        files = [FileOut(**f, url=f"/v1/jobs/{job.id}/files/{f['name']}") for f in job.files]
    return JobOut(
        id=job.id,
        client_job_id=job.client_job_id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        attempts=job.attempts,
        image_count=job.image_count,
        last_error=job.last_error,
        title=job.title,
        relevant=job.relevant,
        files=files,
        completed_at=job.completed_at,
        acked_at=job.acked_at,
        duplicate=duplicate,
    )


# --------------------------------------------------------------- aplicación
def create_app(
    settings: Settings | None = None,
    ai_factory: Callable[[], AIProvider] | None = None,
    start_worker: bool | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    database = Database(settings.db_path)
    storage = Storage(settings)
    renderer = Renderer(settings.chromium_executable)
    push = APNsClient(settings, database)

    def default_ai_factory() -> AIProvider:
        return OpenAIProvider(settings)

    processor = JobProcessor(settings, database, storage, ai_factory or default_ai_factory, renderer, push)
    worker = Worker(processor, settings)
    run_worker = settings.worker_enabled if start_worker is None else start_worker
    ai_ready = ai_factory is not None or not settings.ai_config_problems()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if not settings.token_hashes:
            log.warning("API_TOKENS está vacío: ningún dispositivo podrá autenticarse")
        for p in settings.ai_config_problems():
            log.warning("Configuración de IA incompleta: %s", p)
        if run_worker:
            worker.start()
        yield
        if run_worker:
            worker.stop()

    app = FastAPI(title="AutoGPT Watch API", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = database
    app.state.storage = storage
    app.state.worker = worker
    app.state.processor = processor

    @app.middleware("http")
    async def https_only(request: Request, call_next):
        if settings.require_https:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto != "https":
                return JSONResponse({"detail": "Se requiere HTTPS"}, status_code=403)
        return await call_next(request)

    def owner_of(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Falta el token de dispositivo")
        digest = hash_token(authorization[7:].strip())
        if not any(hmac.compare_digest(digest, h) for h in settings.token_hashes):
            raise HTTPException(401, "Token no válido")
        return digest[:24]

    def get_owned_job(job_id: str, owner: str) -> Job:
        job = database.get_job(job_id, owner)
        if not job:
            raise HTTPException(404, "Trabajo no encontrado")
        return job

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": VERSION,
            "ai_configured": not settings.ai_config_problems(),
            "image_generation_configured": bool(settings.openai_image_model),
            "apns_enabled": settings.apns_enabled,
            "presets": sorted(PRESETS),
        }

    @app.get("/v1/me")
    def me(owner: str = Depends(owner_of)) -> dict[str, Any]:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with database.connect() as conn:
            jobs, images = database.usage_today(conn, owner, day)
        return {
            "owner": owner,
            "usage_today": {"jobs": jobs, "images": images},
            "limits": {
                "max_jobs_per_day": settings.max_jobs_per_day,
                "max_images_per_day": settings.max_images_per_day,
                "max_images_per_job": settings.max_images_per_job,
                "max_upload_mb": settings.max_upload_mb,
            },
            "ai_configured": not settings.ai_config_problems(),
        }

    def _create(owner: str, client_job_id: str, images: list, options: dict[str, Any]) -> JSONResponse:
        existing = database.find_by_client_id(owner, client_job_id)
        if existing:
            return JSONResponse(job_out(existing, duplicate=True).model_dump(), status_code=200)
        hashes = [img.sha256 for img in images]
        if hashes:
            dup = database.find_by_image_hashes(owner, hashes, time.time() - DEDUPE_WINDOW_SECONDS)
            if dup:
                return JSONResponse(job_out(dup, duplicate=True).model_dump(), status_code=200)
        job_id = uuid.uuid4().hex
        if images:
            storage.save_uploads(job_id, images)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            with database.tx() as conn:
                jobs_today, images_today = database.usage_today(conn, owner, day)
                if jobs_today + 1 > settings.max_jobs_per_day:
                    raise HTTPException(429, "Límite diario de trabajos alcanzado")
                if images_today + len(images) > settings.max_images_per_day:
                    raise HTTPException(429, "Límite diario de imágenes alcanzado")
                job = database.create_job(
                    conn,
                    owner=owner,
                    client_job_id=client_job_id,
                    image_hashes=hashes or [f"selftest-{job_id}"],
                    options=options,
                    job_id=job_id,
                    image_count=len(images),
                )
                database.add_usage(conn, owner, day, len(images))
        except HTTPException:
            storage.delete_uploads(job_id)
            raise
        except Exception:
            storage.delete_uploads(job_id)
            again = database.find_by_client_id(owner, client_job_id)  # carrera con petición duplicada
            if again:
                return JSONResponse(job_out(again, duplicate=True).model_dump(), status_code=200)
            raise
        return JSONResponse(job_out(job).model_dump(), status_code=202)

    @app.post("/v1/jobs", status_code=202)
    async def create_job(
        files: list[UploadFile] = File(...),
        client_job_id: str = Form(...),
        consent: bool = Form(False),
        preset: str = Form("watch"),
        language: str = Form("es"),
        allow_illustrations: bool = Form(True),
        delete_uploads: bool = Form(True),
        idempotency_key: str | None = Header(default=None),
        owner: str = Depends(owner_of),
    ) -> JSONResponse:
        client_job_id = (idempotency_key or client_job_id).strip()
        if not CLIENT_ID.match(client_job_id):
            raise HTTPException(400, "client_job_id no válido")
        if not ai_ready:
            raise HTTPException(503, "El servidor no tiene configurada la IA: " + "; ".join(settings.ai_config_problems()))
        if not consent:
            raise HTTPException(400, "Falta el consentimiento del usuario para enviar fotografías al servicio de IA")
        if preset not in PRESETS:
            raise HTTPException(400, f"preset debe ser uno de {sorted(PRESETS)}")
        if language not in {"es", "auto"}:
            raise HTTPException(400, "language debe ser 'es' o 'auto'")
        if not files or len(files) > settings.max_images_per_job:
            raise HTTPException(400, f"Envía entre 1 y {settings.max_images_per_job} imágenes")
        existing = database.find_by_client_id(owner, client_job_id)
        if existing:
            return JSONResponse(job_out(existing, duplicate=True).model_dump(), status_code=200)
        max_bytes = int(settings.max_upload_mb * 1024 * 1024)
        images = []
        for f in files:
            raw = await f.read(max_bytes + 1)
            try:
                images.append(validate_image(raw, settings))
            except UploadRejected as exc:
                raise HTTPException(400, f"{f.filename}: {exc}") from exc
        options = {
            "preset": preset,
            "language": language,
            "allow_illustrations": allow_illustrations,
            "delete_uploads": delete_uploads or settings.delete_uploads_after_processing,
        }
        return _create(owner, client_job_id, images, options)

    @app.post("/v1/selftest", status_code=202)
    def selftest(preset: str = "watch", owner: str = Depends(owner_of)) -> JSONResponse:
        if preset not in PRESETS:
            raise HTTPException(400, "preset no válido")
        return _create(owner, f"selftest-{uuid.uuid4()}", [], {"preset": preset, "selftest": True})

    @app.get("/v1/jobs", response_model=JobList)
    def list_jobs(status: str | None = None, limit: int = 50, owner: str = Depends(owner_of)) -> JobList:
        statuses = {s.strip() for s in status.split(",")} if status else None
        if statuses and not statuses <= dbm.ALL_STATUSES:
            raise HTTPException(400, "estado no válido")
        jobs = database.list_jobs(owner, statuses, max(1, min(limit, 200)))
        return JobList(jobs=[job_out(j) for j in jobs])

    @app.get("/v1/jobs/{job_id}", response_model=JobOut)
    def get_job(job_id: str, owner: str = Depends(owner_of)) -> JobOut:
        return job_out(get_owned_job(job_id, owner))

    @app.get("/v1/jobs/{job_id}/result")
    def get_result(job_id: str, owner: str = Depends(owner_of)) -> dict[str, Any]:
        job = get_owned_job(job_id, owner)
        if job.status not in (dbm.COMPLETED, dbm.ACKNOWLEDGED) or job.result is None:
            raise HTTPException(409, f"El trabajo está en estado {job.status}")
        return {"job": job_out(job).model_dump(), "result": job.result}

    @app.get("/v1/jobs/{job_id}/files/{name}")
    def get_file(job_id: str, name: str, owner: str = Depends(owner_of)) -> FileResponse:
        job = get_owned_job(job_id, owner)
        if job.status not in (dbm.COMPLETED, dbm.ACKNOWLEDGED):
            raise HTTPException(409, f"El trabajo está en estado {job.status}")
        if name not in {f["name"] for f in job.files}:
            raise HTTPException(404, "Archivo no encontrado")
        path = storage.result_file(job_id, name)
        if not path:
            raise HTTPException(410, "El archivo ya fue eliminado del servidor")
        return FileResponse(path, media_type="image/png", filename=name)

    @app.post("/v1/jobs/{job_id}/ack", response_model=JobOut)
    def ack(job_id: str, body: AckIn, owner: str = Depends(owner_of)) -> JobOut:
        job = get_owned_job(job_id, owner)
        expected = {f["name"] for f in job.files}
        missing = expected - set(body.saved)
        if missing:
            raise HTTPException(400, f"Faltan por confirmar: {sorted(missing)}")
        if not database.mark_acknowledged(job_id, owner):
            raise HTTPException(409, f"No se puede confirmar un trabajo en estado {job.status}")
        if settings.result_retention_hours_after_ack <= 0:
            storage.delete_results(job_id)
        return job_out(get_owned_job(job_id, owner))

    @app.post("/v1/jobs/{job_id}/retry", response_model=JobOut)
    def retry(job_id: str, owner: str = Depends(owner_of)) -> JobOut:
        get_owned_job(job_id, owner)
        if not database.requeue_failed(job_id, owner):
            raise HTTPException(409, "Sólo se pueden reintentar trabajos fallidos")
        return job_out(get_owned_job(job_id, owner))

    @app.post("/v1/devices")
    def register_device(body: DeviceIn, owner: str = Depends(owner_of)) -> dict[str, Any]:
        if not APNS_TOKEN.match(body.apns_token):
            raise HTTPException(400, "Token APNs no válido")
        if body.environment not in {"sandbox", "production"}:
            raise HTTPException(400, "environment debe ser sandbox o production")
        database.upsert_device(owner, body.apns_token.lower(), body.environment)
        return {"registered": True, "apns_enabled": settings.apns_enabled}

    return app


def app_factory() -> FastAPI:  # para `uvicorn app.main:app_factory --factory`
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
