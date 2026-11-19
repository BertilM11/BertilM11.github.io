"""Validación de imágenes subidas y gestión de archivos en disco."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings

ALLOWED_FORMATS = {"JPEG", "PNG"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


class UploadRejected(ValueError):
    """La imagen no supera la validación (formato, tamaño, píxeles)."""


@dataclass
class ValidatedImage:
    sha256: str
    jpeg_bytes: bytes
    width: int
    height: int


def validate_image(raw: bytes, settings: Settings) -> ValidatedImage:
    max_bytes = int(settings.max_upload_mb * 1024 * 1024)
    if not raw:
        raise UploadRejected("archivo vacío")
    if len(raw) > max_bytes:
        raise UploadRejected(f"archivo mayor de {settings.max_upload_mb} MB")
    # Comprobación de firma antes de decodificar.
    if not (raw.startswith(b"\xff\xd8\xff") or raw.startswith(b"\x89PNG\r\n\x1a\n")):
        raise UploadRejected("sólo se aceptan JPEG o PNG")
    Image.MAX_IMAGE_PIXELS = settings.max_image_pixels
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in ALLOWED_FORMATS:
            raise UploadRejected(f"formato no permitido: {fmt}")
        with Image.open(io.BytesIO(raw)) as img:
            if img.width * img.height > settings.max_image_pixels:
                raise UploadRejected("imagen con demasiados píxeles")
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            # Reducimos a un tamaño útil para lectura de documentos y eliminamos
            # metadatos (EXIF/GPS) antes de reenviar la imagen al servicio de IA.
            img.thumbnail((2560, 2560))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=90, optimize=True)
            data = out.getvalue()
            width, height = img.size
    except UploadRejected:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise UploadRejected(f"imagen no válida: {exc.__class__.__name__}") from exc
    return ValidatedImage(hashlib.sha256(raw).hexdigest(), data, width, height)


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        settings.results_dir.mkdir(parents=True, exist_ok=True)

    def upload_dir(self, job_id: str) -> Path:
        return self.settings.uploads_dir / job_id

    def result_dir(self, job_id: str) -> Path:
        return self.settings.results_dir / job_id

    def save_uploads(self, job_id: str, images: list[ValidatedImage]) -> list[Path]:
        d = self.upload_dir(job_id)
        d.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, img in enumerate(images, start=1):
            p = d / f"photo-{i:02d}.jpg"
            p.write_bytes(img.jpeg_bytes)
            paths.append(p)
        return paths

    def list_uploads(self, job_id: str) -> list[Path]:
        d = self.upload_dir(job_id)
        return sorted(d.glob("photo-*.jpg")) if d.exists() else []

    def delete_uploads(self, job_id: str) -> None:
        shutil.rmtree(self.upload_dir(job_id), ignore_errors=True)

    def delete_results(self, job_id: str) -> None:
        shutil.rmtree(self.result_dir(job_id), ignore_errors=True)

    def result_file(self, job_id: str, name: str) -> Path | None:
        if not SAFE_NAME.match(name):
            return None
        base = self.result_dir(job_id).resolve()
        p = (base / name).resolve()
        if p.parent != base or not p.is_file():
            return None
        return p
