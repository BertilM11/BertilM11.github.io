# AutoGPT Watch v1.0 (iOS)

Fotografías tomadas con la **Cámara original** del iPhone → análisis con OpenAI en **tu servidor** → respuestas renderizadas como imágenes PNG con aspecto de conversación → guardadas en **Fotos como Favoritas** → sincronizadas con el álbum Favoritos del **Apple Watch**.

No incluye otra cámara, otra galería ni app para watchOS.

```
 iPhone                                         Servidor (FastAPI)                 OpenAI
 ┌────────────────────────────┐   HTTPS +      ┌──────────────────────────────┐
 │ Atajos: Cámara «Se cierra» │   token        │ POST /v1/jobs (idempotente)  │
 │  → ProcessPendingPhotos    │ ─────────────▶ │ cola SQLite persistente      │──▶ Responses API
 │ PhotoKit: fotos de sesión  │  (URLSession   │ worker + reintentos          │    (visión, JSON
 │ Vision: ¿tiene texto?      │   background)  │ Markdown/KaTeX → PNG paginado│◀──  estructurado)
 │ JPEG sin EXIF/GPS          │                │ Graphviz / SVG / gráficas    │──▶ Images API
 │                            │ ◀───────────── │ push APNs (silenciosa/aviso) │    (sólo si se pide)
 │ descarga + SHA-256         │   GET files    │ GET /files · POST /ack       │
 │ PhotoKit: isFavorite=true  │                └──────────────────────────────┘
 └────────────────────────────┘
          │  Favoritos
          ▼
   Apple Watch (app Fotos)
```

## Estructura

| Carpeta | Contenido |
|---|---|
| `ios/` | Proyecto Xcode (`AutoGPTWatch.xcodeproj`), app SwiftUI, paquete `Packages/AutoGPTCore` con la lógica probada por XCTest |
| `backend/` | API FastAPI, cola persistente, integración OpenAI, renderizador, APNs, Dockerfile y docker-compose con HTTPS |
| `tests/` | Pruebas del backend (unitarias, integración y contrato iOS↔backend). Las pruebas Swift están en `ios/Packages/AutoGPTCore/Tests` |
| `docs/` | Guías de despliegue, compilación, Atajos, Apple Watch y lista de validación en dispositivo |

## Puesta en marcha (resumen)

1. **Servidor**: [docs/backend.md](docs/backend.md). Necesitas un dominio con HTTPS, `OPENAI_API_KEY`, un modelo con visión en `OPENAI_MODEL` y al menos un token en `API_TOKENS`.
2. **App iOS**: [docs/ios-build.md](docs/ios-build.md). Requiere un Mac con Xcode 16 o posterior y un iPhone con iOS 17 o posterior.
3. **Automatización**: [docs/shortcuts-automation.md](docs/shortcuts-automation.md) (Cámara → Se cierra → Procesar fotos pendientes).
4. **Apple Watch**: [docs/apple-watch.md](docs/apple-watch.md) (app Watch → Fotos → Álbum sincronizado: Favoritas).
5. En la app: Configuración → servidor y token → **Prueba de funcionamiento** → activa el interruptor.

## Estado real de la validación

| Parte | Estado |
|---|---|
| Backend: API, cola, reintentos, límites, idempotencia, limpieza | ✅ Probado aquí (56 pruebas con pytest) |
| Renderizado Markdown/LaTeX/tablas/código → PNG paginado (Chromium) | ✅ Probado aquí con Chromium real; las imágenes se revisaron a ojo |
| Graphviz, SVG saneado, gráficas | ✅ Probado aquí |
| Formato de la petición a OpenAI | ✅ Verificado contra los tipos del SDK `openai==3.55.1` y con pruebas de forma |
| **Llamada real a OpenAI** | ⏳ **Pendiente**: aquí no hay clave ni acceso a la documentación de OpenAI. Valida el nombre del modelo y haz una petición real |
| APNs | ✅ Formato de petición probado con transporte simulado · ⏳ entrega real pendiente |
| Contrato iOS↔backend (multipart, claves JSON) | ✅ Probado (réplica byte a byte del multipart Swift) |
| App iOS (Swift) | ⚠️ **Escrita, sin compilar**: este entorno es Linux sin Swift ni Xcode. Se comprobó la sintaxis de los 31 archivos con tree-sitter y se revisó a mano la API de iOS |
| Pruebas XCTest de `AutoGPTCore` | ⏳ Escritas, sin ejecutar (`swift test` en un Mac) |
| PhotoKit, Vision, App Intents, Atajos, push, segundo plano, Apple Watch | ⏳ Pendiente en iPhone físico: ver [docs/validation-checklist.md](docs/validation-checklist.md) |

## Limitaciones reales (iOS y watchOS)

- **Tiempo en segundo plano**: el App Intent dispone de pocos segundos. Envía las fotos, cuya subida sigue en una `URLSession` en segundo plano, y recoge lo que ya esté listo. El análisis tarda más, así que el resultado se guarda cuando ocurre una de estas cosas:
  - llega la push silenciosa del servidor, si iOS la entrega;
  - vuelves a cerrar la Cámara;
  - abres la app;
  - iOS ejecuta el refresco en segundo plano, cuando él decide;
  - tocas la notificación de aviso, que el servidor envía si el iPhone no confirma el guardado en 2 minutos.

  **No hay garantía de que todo ocurra sin tocar el iPhone.**
- **Push**: requiere una cuenta de Apple Developer de pago. Las push silenciosas están limitadas por iOS y no se entregan si el usuario cerró la app a la fuerza.
- **Apple Watch**: watchOS sincroniza Favoritos cuando decide, a menudo cargando, y no hay API para forzarlo. Puede tardar minutos.
- **«Sólo fotos de la Cámara»**: PhotoKit no expone qué app creó una foto. Se usa una heurística: se excluyen capturas de pantalla, PNG y resultados propios, y se exige EXIF `Make=Apple` con modelo o lente de iPhone. Una foto de iPhone recibida por AirDrop durante la sesión podría pasar el filtro.
- **Guardado bloqueado**: si el iPhone está bloqueado justo tras reiniciarse, el Llavero o Fotos pueden no estar disponibles. El trabajo se conserva y se reintenta.
- Existe una ventana muy pequeña, si la app muere justo entre guardar en Fotos y registrarlo localmente, en la que una respuesta podría guardarse dos veces.

## Uso responsable

La app envía fotos a un servicio de IA de terceros a través de tu servidor, con consentimiento explícito previo. No la uses con documentos que no tengas derecho a compartir ni para infringir normas de exámenes o evaluaciones.
