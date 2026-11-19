"""Fixtures de pruebas del backend.

`FakeAI` es un DOBLE DE PRUEBA: sólo existe en los tests para no depender de la red
ni gastar créditos. Nunca se usa en el código de producción.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai import Analysis, PermanentAIError, TransientAIError, Visual  # noqa: E402
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

TOKEN = "test-device-token-0123456789"


def chromium_path() -> str:
    env = os.environ.get("CHROMIUM_EXECUTABLE")
    if env:
        return env
    for cand in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome"):
        return str(cand)
    return ""  # Playwright usará su navegador instalado


class FakeAI:
    """Doble de prueba del proveedor de IA (configurable por test)."""

    def __init__(self):
        self.calls = 0
        self.image_calls = 0
        self.errors: list[Exception] = []
        self.analysis = Analysis(
            is_relevant=True,
            title="Ejercicio de prueba",
            answer_markdown="## Ejercicio 1\n\nSi $x^2=4$ entonces $$x=\\pm 2$$\n\n| a | b |\n|---|---|\n| 1 | 2 |",
            visuals=[Visual(kind="graphviz", title="Grafo", code="digraph { a -> b }")],
            model="fake-model",
        )

    def analyze(self, images, options):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.analysis

    def generate_image(self, prompt, size):
        self.image_calls += 1
        img = Image.new("RGB", (64, 96), "orange")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="",
        openai_model="",
        api_tokens=TOKEN,
        data_dir=tmp_path / "data",
        worker_enabled=False,
        chromium_executable=chromium_path(),
        retry_base_seconds=0.0,
        max_attempts=3,
        max_jobs_per_day=5,
        max_images_per_day=8,
        max_images_per_job=4,
        max_upload_mb=2.0,
        result_retention_hours_after_ack=24,
    )


@pytest.fixture
def fake_ai() -> FakeAI:
    return FakeAI()


@pytest.fixture
def app(settings, fake_ai):
    return create_app(settings, ai_factory=lambda: fake_ai, start_worker=False)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


def jpeg_bytes(color="white", size=(800, 600), text_block=True, exif_gps=False) -> bytes:
    img = Image.new("RGB", size, color)
    if text_block:
        from PIL import ImageDraw

        d = ImageDraw.Draw(img)
        for i in range(10):
            d.text((20, 20 + i * 40), f"Ejercicio {i}: resuelve x^2 = {i}", fill="black")
    buf = io.BytesIO()
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {1: "N", 2: (40.0, 26.0, 46.0)}  # GPSInfo
        exif[0x010F] = "Apple"
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def has_graphviz() -> bool:
    return shutil.which("dot") is not None


__all__ = ["FakeAI", "TOKEN", "jpeg_bytes", "PermanentAIError", "TransientAIError", "has_graphviz"]
