"""Contrato iOS ↔ backend.

No se puede ejecutar Swift en este entorno, así que se reproduce aquí, byte a byte, el
cuerpo multipart que genera `MultipartFormBuilder` / `APIRequestFactory.createJobBody`
(ios/Packages/AutoGPTCore/Sources/AutoGPTCore/APIRequests.swift) y se comprueba que el
servidor lo acepta y que sus respuestas contienen todas las claves que decodifica
`ServerJob`, `ServerHealth` y `ServerMe` (APIModels.swift).
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import jpeg_bytes

SWIFT = Path(__file__).resolve().parents[2] / "ios" / "Packages" / "AutoGPTCore" / "Sources" / "AutoGPTCore"


def swift_multipart(boundary: str, fields: list[tuple[str, str]], files: list[tuple[str, str, bytes]]) -> bytes:
    """Réplica de MultipartFormBuilder.addField/addFile/finalize."""
    body = b""
    for name, value in fields:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += value.encode() + b"\r\n"
    for name, filename, data in files:
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        body += b"Content-Type: image/jpeg\r\n\r\n"
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body


def swift_coding_keys(struct_name: str, nested: bool = False) -> set[str]:
    """Extrae las claves JSON del `enum CodingKeys` propio de un struct de APIModels.swift."""
    src = (SWIFT / "APIModels.swift").read_text()
    start = src.index(f"struct {struct_name}")
    block = src[start:]
    indent = " " * (8 if nested else 4)
    ck = block.index(f"\n{indent}enum CodingKeys") + 1
    body = block[ck: block.index("}", ck)]
    keys = set()
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("case "):
            continue
        for part in line[5:].split(","):
            part = part.strip()
            m = re.match(r'(\w+)\s*=\s*"([^"]+)"', part)
            keys.add(m.group(2) if m else part)
    return keys


def test_swift_builder_source_matches_replica():
    """Si alguien cambia el formato en Swift, este test obliga a revisar el contrato."""
    src = (SWIFT / "APIRequests.swift").read_text()
    for snippet in [
        r'"--\(boundary)\r\n"',
        r'"Content-Disposition: form-data; name=\"\(Self.escape(name))\"\r\n\r\n"',
        r'"Content-Type: \(mimeType)\r\n\r\n"',
        r'"--\(boundary)--\r\n"',
        'b.addField("client_job_id", clientJobID)',
        'b.addField("consent", consent ? "true" : "false")',
        'b.addField("preset", options.preset.rawValue)',
        'b.addField("language", options.language.rawValue)',
        'b.addField("allow_illustrations", options.allowIllustrations ? "true" : "false")',
        'b.addField("delete_uploads", options.deleteUploads ? "true" : "false")',
        'b.addFile("files", filename: String(format: "photo-%02d.jpg", i + 1), mimeType: "image/jpeg", data: data)',
        'r.setValue(clientJobID, forHTTPHeaderField: "Idempotency-Key")',
    ]:
        assert snippet in src, f"El formato Swift cambió: {snippet}"


def test_server_accepts_ios_upload_and_returns_decodable_job(client, app):
    boundary = "AutoGPTWatch-1B4E28BA-2FA1-11D2-883F-0016D3CCA427"
    cid = "1B4E28BA-2FA1-11D2-883F-0016D3CCA427"  # UUID().uuidString en iOS
    body = swift_multipart(
        boundary,
        [
            ("client_job_id", cid),
            ("consent", "true"),
            ("preset", "watch"),
            ("language", "es"),
            ("allow_illustrations", "true"),
            ("delete_uploads", "true"),
        ],
        [("files", "photo-01.jpg", jpeg_bytes()), ("files", "photo-02.jpg", jpeg_bytes(color=(200, 200, 255)))],
    )
    r = client.post(
        "/v1/jobs",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Idempotency-Key": cid},
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["client_job_id"] == cid
    assert job["image_count"] == 2
    assert swift_coding_keys("ServerJob") <= set(job), "faltan claves que ServerJob necesita"

    app.state.worker.run_once()
    done = client.get(f"/v1/jobs/{job['id']}").json()
    assert done["status"] == "completed"
    file_keys = {"name", "kind", "index", "title", "bytes", "sha256", "url"}  # ServerFile
    for f in done["files"]:
        assert file_keys <= set(f)
        assert f["url"].startswith("/v1/jobs/")

    # Reintento de la subida en segundo plano (misma Idempotency-Key) -> mismo trabajo
    again = client.post(
        "/v1/jobs",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Idempotency-Key": cid},
    )
    assert again.status_code == 200
    assert again.json()["id"] == job["id"]


def test_health_and_me_match_swift_models(client):
    health = client.get("/health").json()
    assert swift_coding_keys("ServerHealth") <= set(health)
    me = client.get("/v1/me").json()
    assert swift_coding_keys("ServerMe") == {"owner", "usage_today", "limits", "ai_configured"}
    assert swift_coding_keys("ServerMe") <= set(me)
    assert swift_coding_keys("Limits", nested=True) <= set(me["limits"])


def test_ack_body_format_from_swift(client, app):
    # APIRequestFactory.ack envía {"saved": [...]} como JSON
    src = (SWIFT / "APIRequests.swift").read_text()
    assert '["saved": savedNames]' in src
    assert '"apns_token": apnsToken' in src and '"environment": sandbox ? "sandbox" : "production"' in src
