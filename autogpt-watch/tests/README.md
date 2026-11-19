# Pruebas

| Ubicación | Qué cubre | Cómo ejecutar | Estado |
|---|---|---|---|
| `tests/backend/test_api.py` | Integración: autenticación, HTTPS, consentimiento, validación, idempotencia, deduplicación, límites, flujo completo (crear → procesar → descargar → ack), reintentos, fallos permanentes, caché del análisis, recuperación de trabajos colgados, visuales, ilustraciones, caducidad, selftest, dispositivos | `backend/.venv/bin/python -m pytest` | ✅ pasan |
| `tests/backend/test_units.py` | Markdown seguro, fórmulas, paginación sin cortar líneas, EXIF, path traversal, saneado SVG/DOT, Graphviz, render con Chromium, esquema estricto de OpenAI, forma de la petición, clasificación de errores, APNs | idem | ✅ pasan |
| `tests/backend/test_ios_contract.py` | Contrato iOS↔backend: multipart idéntico al de Swift, claves JSON de `ServerJob`/`ServerHealth`/`ServerMe` | idem | ✅ pasan |
| `ios/Packages/AutoGPTCore/Tests` | Selección de fotos, heurística de cámara, filtro Vision, reintentos, puerta de la automatización, transiciones de fase, peticiones HTTP, multipart, decodificación | `cd ios/Packages/AutoGPTCore && swift test` (macOS) | ⏳ sin ejecutar: no hay Swift en este entorno |

En los tests, OpenAI se sustituye por un doble de prueba (`FakeAI`) que sólo existe dentro de `tests/`. El código de producción nunca usa respuestas simuladas.
