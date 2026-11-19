"""Configuración del backend, leída exclusivamente de variables de entorno.

La clave de OpenAI vive SOLO aquí (variable OPENAI_API_KEY). Nunca se envía al
cliente iOS ni se registra en logs.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- OpenAI -------------------------------------------------------------
    openai_api_key: str = Field(default="", repr=False)
    # Sin valores por defecto inventados: el operador debe elegir modelos vigentes
    # en https://platform.openai.com/docs/models y fijarlos en el entorno.
    openai_model: str = ""
    openai_image_model: str = ""
    openai_reasoning_effort: str = ""  # opcional: "low" | "medium" | "high" ... (sólo si el modelo lo admite)
    openai_max_output_tokens: int = 16000
    openai_timeout_seconds: float = 300.0
    openai_image_detail: str = "high"

    # --- Autenticación de dispositivos ---------------------------------------
    # Lista separada por comas de tokens de dispositivo (generar con scripts/new_token.py).
    api_tokens: str = Field(default="", repr=False)

    # --- Almacenamiento -------------------------------------------------------
    data_dir: Path = Path("./data")
    delete_uploads_after_processing: bool = True
    result_retention_hours_after_ack: float = 24.0
    unacked_result_retention_hours: float = 24.0 * 7

    # --- Límites --------------------------------------------------------------
    max_images_per_job: int = 6
    max_upload_mb: float = 12.0
    max_image_pixels: int = 40_000_000
    max_jobs_per_day: int = 60
    max_images_per_day: int = 200
    max_generated_images_per_job: int = 2

    # --- Cola -----------------------------------------------------------------
    worker_enabled: bool = True
    worker_poll_seconds: float = 1.0
    worker_concurrency: int = 2
    max_attempts: int = 4
    retry_base_seconds: float = 15.0
    stale_job_seconds: float = 900.0

    # --- Renderizado ----------------------------------------------------------
    chromium_executable: str = ""  # vacío = el de Playwright

    # --- HTTPS ----------------------------------------------------------------
    # Si es true, se rechazan peticiones que no lleguen por HTTPS (directo o vía proxy
    # que envíe X-Forwarded-Proto: https).
    require_https: bool = False

    # --- APNs (opcional; requiere cuenta de Apple Developer de pago) -----------
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = ""
    apns_key_path: str = ""
    # Si el iPhone no confirma el guardado tras este tiempo, se envía una
    # notificación visible para que el usuario termine el guardado con un toque.
    apns_alert_delay_seconds: float = 120.0

    @field_validator("openai_image_detail")
    @classmethod
    def _detail(cls, v: str) -> str:
        if v not in {"low", "high", "auto", "original"}:
            raise ValueError("openai_image_detail debe ser low, high, auto u original")
        return v

    # ------------------------------------------------------------------------
    @property
    def token_hashes(self) -> set[str]:
        return {hash_token(t.strip()) for t in self.api_tokens.split(",") if t.strip()}

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "autogpt_watch.sqlite3"

    @property
    def apns_enabled(self) -> bool:
        return all([self.apns_key_id, self.apns_team_id, self.apns_bundle_id, self.apns_key_path])

    def ai_config_problems(self) -> list[str]:
        problems = []
        if not self.openai_api_key:
            problems.append("Falta OPENAI_API_KEY")
        if not self.openai_model:
            problems.append("Falta OPENAI_MODEL (elige un modelo vigente con visión)")
        return problems


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@lru_cache
def get_settings() -> Settings:
    return Settings()
