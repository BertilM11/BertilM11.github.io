"""Cola persistente de trabajos: procesamiento, reintentos y mantenimiento."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from PIL import Image

from .ai import AIProvider, Analysis, PermanentAIError, TransientAIError, parse_analysis
from .config import Settings
from .db import Database, Job
from .push import APNsClient
from .render.renderer import Renderer
from .render.visuals import VisualError, graphviz_to_svg, plot_to_png, sanitize_svg
from .render.theme import PRESETS
from .selftest import selftest_analysis
from .storage import Storage

log = logging.getLogger("autogpt.worker")


def backoff_delay(attempt: int, base: float) -> float:
    """Retroceso exponencial con jitter: base, 2·base, 4·base... (máx. 30 min)."""
    return min(1800.0, base * (2 ** max(0, attempt - 1))) * random.uniform(0.8, 1.2)


def _thumb(jpeg: bytes, height: int = 220) -> bytes:
    with Image.open(io.BytesIO(jpeg)) as img:
        img = img.convert("RGB")
        img.thumbnail((height * 2, height))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)
        return out.getvalue()


class JobProcessor:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        storage: Storage,
        ai_factory,
        renderer: Renderer,
        push: APNsClient,
    ):
        self.settings = settings
        self.db = db
        self.storage = storage
        self.ai_factory = ai_factory  # callable -> AIProvider (diferido para no fallar al arrancar)
        self.renderer = renderer
        self.push = push

    @contextmanager
    def _heartbeat(self, job_id: str) -> Iterator[None]:
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(30):
                try:
                    self.db.heartbeat(job_id)
                except Exception:  # noqa: BLE001
                    log.exception("heartbeat")

        t = threading.Thread(target=beat, daemon=True)
        t.start()
        try:
            yield
        finally:
            stop.set()

    # ----------------------------------------------------------------------
    def process(self, job: Job) -> None:
        try:
            with self._heartbeat(job.id):
                self._run(job)
        except PermanentAIError as exc:
            log.warning("job %s falló (permanente): %s", job.id, exc)
            self.db.mark_failed(job.id, str(exc))
        except Exception as exc:  # noqa: BLE001 - incluye TransientAIError y fallos de render
            msg = f"{exc.__class__.__name__}: {exc}"
            if job.attempts >= self.settings.max_attempts:
                log.warning("job %s agotó reintentos: %s", job.id, msg)
                self.db.mark_failed(job.id, f"Agotados {job.attempts} intentos. Último error: {msg}")
            else:
                delay = backoff_delay(job.attempts, self.settings.retry_base_seconds)
                log.info("job %s reintento en %.0fs: %s", job.id, delay, msg)
                self.db.mark_retry(job.id, msg, delay)
            if not isinstance(exc, TransientAIError):
                log.exception("error inesperado procesando %s", job.id)

    def _analysis(self, job: Job) -> Analysis:
        """Reutiliza el análisis ya pagado si un reintento ocurre después de la llamada a OpenAI."""
        if job.options.get("selftest"):
            return selftest_analysis()
        rdir = self.storage.result_dir(job.id)
        cache = rdir / "analysis.json"
        if cache.exists():
            data = json.loads(cache.read_text())
            return parse_analysis(data, model=data.get("model", ""))
        uploads = self.storage.list_uploads(job.id)
        if not uploads:
            raise PermanentAIError("Las fotografías temporales ya no están disponibles en el servidor")
        analysis = self.ai_factory().analyze(uploads, job.options)
        rdir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(analysis.to_dict(), ensure_ascii=False))
        return analysis

    def _run(self, job: Job) -> None:
        ai: AIProvider | None = None
        analysis = self._analysis(job)
        preset = job.options.get("preset", "watch")
        if preset not in PRESETS:
            preset = "watch"
        rdir = self.storage.result_dir(job.id)
        rdir.mkdir(parents=True, exist_ok=True)
        for old in rdir.glob("*.png"):
            old.unlink()

        files: list[dict[str, Any]] = []
        warnings: list[str] = []
        if not analysis.is_relevant:
            self._finish(job, analysis, files, warnings, relevant=False)
            return

        # 1) Visuales (antes del texto para poder avisar de fallos dentro de la respuesta).
        visual_pngs: list[tuple[str, bytes]] = []
        generated = 0
        width_px = PRESETS[preset].css_width * PRESETS[preset].dpr
        for v in analysis.visuals[:8]:
            try:
                if v.kind == "graphviz":
                    png = self.renderer.svg_to_png(graphviz_to_svg(v.code or ""), preset)
                elif v.kind == "svg":
                    png = self.renderer.svg_to_png(sanitize_svg(v.code or ""), preset)
                elif v.kind == "plot":
                    png = plot_to_png(v.title, v.x_label, v.y_label, v.series, width_px)
                elif v.kind == "illustration":
                    if not job.options.get("allow_illustrations", True):
                        continue
                    if generated >= self.settings.max_generated_images_per_job:
                        warnings.append(f"Se omitió «{v.title}»: límite de imágenes generadas por trabajo.")
                        continue
                    ai = ai or self.ai_factory()
                    png = ai.generate_image(v.prompt or v.title, "1024x1536")
                    generated += 1
                else:
                    continue
                visual_pngs.append((v.title, png))
            except (VisualError, PermanentAIError, TransientAIError) as exc:
                log.warning("visual '%s' falló: %s", v.title, exc)
                warnings.append(f"No se pudo generar la imagen «{v.title}»: {exc}")

        markdown = analysis.answer_markdown
        if warnings:
            markdown += "\n\n---\n\n" + "\n".join(f"> ⚠️ {w}" for w in warnings)

        # 2) Respuesta paginada.
        thumbs = [_thumb(p.read_bytes()) for p in self.storage.list_uploads(job.id)[:4]]
        n_photos = job.image_count
        if job.options.get("selftest"):
            prompt = "Prueba de funcionamiento"
        else:
            prompt = "Resuelve esta foto" if n_photos == 1 else f"Resuelve estas {n_photos} fotos"
        pages, math_errors = self.renderer.render_answer(
            markdown, preset_name=preset, title=analysis.title, photo_thumbs=thumbs, prompt=prompt
        )
        if math_errors:
            warnings.extend(f"Fórmula no renderizada: {e[:120]}" for e in math_errors[:5])

        seq = 1
        for page in pages:
            name = f"{seq:02d}-respuesta-{page.index}de{page.total}.png"
            files.append(self._write(job.id, name, page.png, "answer_page", page.index, analysis.title))
            seq += 1
        for k, (title, png) in enumerate(visual_pngs, start=1):
            framed = self.renderer.frame_visual(png, preset, title, f"Imagen {k}/{len(visual_pngs)}")
            name = f"{seq:02d}-imagen-{k}.png"
            files.append(self._write(job.id, name, framed, "visual", k, title))
            seq += 1
        self._finish(job, analysis, files, warnings, relevant=True)

    def _write(self, job_id: str, name: str, data: bytes, kind: str, index: int, title: str) -> dict[str, Any]:
        path = self.storage.result_dir(job_id) / name
        path.write_bytes(data)
        return {
            "name": name,
            "kind": kind,
            "index": index,
            "title": title,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    def _finish(self, job: Job, analysis: Analysis, files, warnings, relevant: bool) -> None:
        result = {
            "title": analysis.title,
            "markdown": analysis.answer_markdown,
            "relevant": relevant,
            "irrelevant_reason": analysis.irrelevant_reason,
            "warnings": warnings,
            "model": analysis.model,
        }
        self.db.mark_completed(job.id, title=analysis.title, relevant=relevant, result=result, files=files)
        if job.options.get("delete_uploads", self.settings.delete_uploads_after_processing):
            self.storage.delete_uploads(job.id)
        done = self.db.get_job(job.id)
        if done and self.push.notify_completed(done):
            self.db.set_flag(job.id, "push_sent")

    # ------------------------------------------------------------ mantenimiento
    def maintenance(self) -> None:
        self.db.requeue_stale(self.settings.stale_job_seconds)
        now = time.time()
        if self.push.enabled:
            for job in self.db.jobs_needing_alert(now - self.settings.apns_alert_delay_seconds):
                self.push.notify_needs_attention(job)
                self.db.set_flag(job.id, "alert_sent")
        acked_before = now - self.settings.result_retention_hours_after_ack * 3600
        unacked_before = now - self.settings.unacked_result_retention_hours * 3600
        for job in self.db.jobs_to_expire(acked_before, unacked_before):
            self.storage.delete_results(job.id)
            self.storage.delete_uploads(job.id)
            self.db.mark_expired(job.id)


class Worker:
    """Hilos de fondo que consumen la cola SQLite."""

    def __init__(self, processor: JobProcessor, settings: Settings):
        self.processor = processor
        self.settings = settings
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        self.processor.db.requeue_stale(0)  # al arrancar, nada puede estar procesándose
        for i in range(max(1, self.settings.worker_concurrency)):
            t = threading.Thread(target=self._loop, name=f"worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        m = threading.Thread(target=self._maintenance_loop, name="maintenance", daemon=True)
        m.start()
        self._threads.append(m)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)

    def run_once(self) -> bool:
        job = self.processor.db.claim_next()
        if not job:
            return False
        self.processor.process(job)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.run_once():
                    self._stop.wait(self.settings.worker_poll_seconds)
            except Exception:  # noqa: BLE001
                log.exception("bucle del worker")
                self._stop.wait(5)

    def _maintenance_loop(self) -> None:
        while not self._stop.wait(30):
            try:
                self.processor.maintenance()
            except Exception:  # noqa: BLE001
                log.exception("mantenimiento")
