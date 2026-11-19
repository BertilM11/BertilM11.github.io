"""Notificaciones APNs (opcional).

- Push silenciosa (apns-push-type: background, content-available: 1) en cuanto el
  trabajo termina: iOS *puede* despertar la app para descargar y guardar. Apple la
  limita y no garantiza su entrega.
- Si el iPhone no confirma el guardado tras APNS_ALERT_DELAY_SECONDS, se envía una
  notificación visible para que el usuario la toque y la app termine el guardado.

Requiere una clave .p8 de APNs (cuenta de Apple Developer de pago).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

import httpx
import jwt

from .config import Settings
from .db import Database, Job

log = logging.getLogger("autogpt.push")


class APNsClient:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.apns_enabled

    def _jwt(self) -> str:
        with self._lock:
            if self._token and time.time() - self._token[1] < 45 * 60:
                return self._token[0]
            key = Path(self.settings.apns_key_path).read_text()
            token = jwt.encode(
                {"iss": self.settings.apns_team_id, "iat": int(time.time())},
                key,
                algorithm="ES256",
                headers={"kid": self.settings.apns_key_id},
            )
            self._token = (token, time.time())
            return token

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(http2=True, timeout=15)
        return self._client

    def _send(self, device_token: str, environment: str, payload: dict, push_type: str, priority: int) -> bool:
        host = "api.sandbox.push.apple.com" if environment == "sandbox" else "api.push.apple.com"
        headers = {
            "authorization": f"bearer {self._jwt()}",
            "apns-topic": self.settings.apns_bundle_id,
            "apns-push-type": push_type,
            "apns-priority": str(priority),
        }
        try:
            r = self._http().post(f"https://{host}/3/device/{device_token}", headers=headers, content=json.dumps(payload))
        except httpx.HTTPError as exc:
            log.warning("APNs error de red: %s", exc)
            return False
        if r.status_code == 200:
            return True
        reason = ""
        try:
            reason = r.json().get("reason", "")
        except ValueError:
            pass
        log.warning("APNs %s: %s", r.status_code, reason)
        if r.status_code == 410 or reason in {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}:
            self.db.remove_device(device_token)
        return False

    def notify_completed(self, job: Job) -> bool:
        if not self.enabled:
            return False
        payload = {"aps": {"content-available": 1}, "job_id": job.id, "event": "job_completed"}
        sent = False
        for token, env in self.db.devices_for(job.owner):
            sent |= self._send(token, env, payload, "background", 5)
        return sent

    def notify_needs_attention(self, job: Job) -> bool:
        if not self.enabled:
            return False
        title = job.title or "Respuestas listas"
        payload = {
            "aps": {
                "alert": {"title": "AutoGPT Watch", "body": f"{title}: toca para guardar las respuestas en Fotos."},
                "sound": "default",
                "content-available": 1,
                "thread-id": "autogpt-results",
            },
            "job_id": job.id,
            "event": "job_needs_save",
        }
        sent = False
        for token, env in self.db.devices_for(job.owner):
            sent |= self._send(token, env, payload, "alert", 10)
        return sent
