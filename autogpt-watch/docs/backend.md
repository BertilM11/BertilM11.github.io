# Backend: despliegue y funcionamiento

## Requisitos
- Un servidor Linux con Docker y un dominio que apunte a él (para el HTTPS de Let's Encrypt).
- Una clave de API de OpenAI con acceso a un modelo con visión y, si quieres ilustraciones, a un modelo de imágenes.

## Despliegue con Docker (HTTPS automático)
```bash
cd backend
cp .env.example .env
python3 scripts/new_token.py          # genera un token de dispositivo
# edita .env: OPENAI_API_KEY, OPENAI_MODEL, OPENAI_IMAGE_MODEL, API_TOKENS=<token>
DOMAIN=api.tudominio.com docker compose up -d --build
curl https://api.tudominio.com/health
```
Caddy obtiene el certificado TLS y hace de proxy inverso hacia `api:8000`. Con `REQUIRE_HTTPS=true`, el backend rechaza peticiones que no lleguen por HTTPS.

### Modelos
Los nombres de modelo **no tienen valor por defecto**. El servidor arranca, pero `POST /v1/jobs` responde 503 hasta que se configuren. `.env.example` propone `gpt-5.5` y `gpt-image-2`, tomados de la lista de modelos del SDK `openai==3.55.1`. **Verifícalos** en https://platform.openai.com/docs/models antes de usarlos. Este entorno de desarrollo no tenía acceso a esa página.

### Push (opcional)
1. En developer.apple.com → Keys, crea una clave con *Apple Push Notifications service* y descarga el `.p8`.
2. Móntala en el contenedor (descomenta la línea en `docker-compose.yml`) y define `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_BUNDLE_ID` (el bundle id de tu app) y `APNS_KEY_PATH`.
3. Cada iPhone indica al registrarse si usa *sandbox* (las builds Debug instaladas desde Xcode) o *production*.

## Ejecución local sin Docker
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium     # o define CHROMIUM_EXECUTABLE
sudo apt-get install graphviz                         # para diagramas
API_TOKENS=dev-token OPENAI_API_KEY=sk-... OPENAI_MODEL=... \
  .venv/bin/uvicorn app.main:app_factory --factory --port 8000
```
La app iOS exige `https://`. Para probar contra un servidor local usa un túnel con HTTPS, por ejemplo Cloudflare Tunnel o ngrok.

## API
Todas las rutas `/v1/*` requieren `Authorization: Bearer <token de dispositivo>`.

| Método y ruta | Descripción |
|---|---|
| `GET /health` | Estado, versión y si la IA y APNs están configurados (sin autenticación) |
| `GET /v1/me` | Valida el token; devuelve el consumo del día y los límites |
| `POST /v1/jobs` | multipart: `files[]` (JPEG/PNG), `client_job_id`, `consent=true`, `preset` (`watch`/`phone`), `language` (`es`/`auto`), `allow_illustrations`, `delete_uploads`. Cabecera opcional `Idempotency-Key`. 202 si es nuevo; 200 con `duplicate=true` si ya existía (mismo id o mismas imágenes) |
| `GET /v1/jobs?status=completed,failed` | Lista de trabajos (para recuperarlos) |
| `GET /v1/jobs/{id}` | Estado: `queued`, `processing`, `completed`, `failed`, `acknowledged` o `expired`, más la lista de archivos con su SHA-256 |
| `GET /v1/jobs/{id}/result` | Markdown original, avisos y modelo usado |
| `GET /v1/jobs/{id}/files/{name}` | Descarga de un PNG |
| `POST /v1/jobs/{id}/ack` | `{"saved": [nombres]}`: confirma que todo está en Fotos (debe incluir todos los archivos) |
| `POST /v1/jobs/{id}/retry` | Vuelve a encolar un trabajo fallido |
| `POST /v1/devices` | `{"apns_token", "environment"}` |
| `POST /v1/selftest` | Trabajo de PRUEBA de renderizado, sin IA, para validar descarga y Favoritos |

## Procesamiento
1. Validación: firma JPEG/PNG, tamaño, píxeles. La imagen se recodifica a JPEG ≤2560 px **sin EXIF ni GPS**.
2. Límites diarios por token (trabajos e imágenes).
3. Cola SQLite: el worker reclama trabajos de forma atómica y actualiza un *heartbeat*. Al reiniciar, los trabajos que quedaron a medias se vuelven a encolar.
4. OpenAI Responses API con `input_image` (data URL) y salida JSON estricta (`text.format = json_schema`, `strict: true`), con `store: false`.
5. El análisis se guarda en caché: si el render falla después, el reintento **no vuelve a pagar** la llamada a OpenAI.
6. Visuales deterministas: Graphviz (se bloquean `image`, `shapefile`, `URL` y `<IMG>`), SVG saneado (sin scripts, `on*` ni recursos externos) y gráficas con matplotlib. Las ilustraciones con la Images API sólo se generan si la pregunta lo pide y el usuario lo permite (máximo `MAX_GENERATED_IMAGES_PER_JOB`).
7. Render: Markdown → HTML sin HTML crudo → KaTeX y Pygments en Chromium **sin red**. Se calculan cortes de página que no parten líneas, fórmulas ni filas, se evita dejar títulos huérfanos y cada página lleva cabecera «n/N».
8. Reintentos: errores transitorios (red, 429, 5xx) con retroceso exponencial (`MAX_ATTEMPTS`). Los errores permanentes (configuración, rechazo del modelo, respuesta incompleta) marcan el trabajo como fallido con el motivo.
9. Limpieza: las fotos se borran tras procesarse (configurable); los resultados se borran `RESULT_RETENTION_HOURS_AFTER_ACK` horas después del ack, o a los 7 días si nunca se confirman.

## Pruebas
```bash
cd autogpt-watch
backend/.venv/bin/python -m pytest          # 56 pruebas
```
Las pruebas sustituyen OpenAI por un **doble de prueba** (`tests/backend/conftest.py::FakeAI`). El renderizado, Graphviz, la base de datos y la API son reales.
