# Validación pendiente en Mac e iPhone físico

El código iOS se escribió en un entorno Linux **sin compilador Swift ni Xcode**. Se verificó:
- la sintaxis de los 31 archivos Swift con tree-sitter;
- el proyecto Xcode con un parser de pbxproj independiente;
- el contrato de red con pruebas en Python.

Nada de lo siguiente se ha ejecutado todavía. Marca cada punto al validarlo.

## Compilación
- [ ] `swift test` en `ios/Packages/AutoGPTCore`: las 14 pruebas XCTest pasan.
- [ ] El proyecto abre en Xcode 16 o posterior y resuelve el paquete local.
- [ ] Compila sin errores en Swift 5. Anota los avisos de concurrencia: con Swift 6 estricto habría que ajustarlos.
- [ ] Se instala en el iPhone con tu Team y bundle id.

## Fase A: interruptor, permisos y detección
- [ ] El interruptor pide consentimiento, después acceso completo a Fotos y notificaciones.
- [ ] Con acceso **limitado**, la app lo indica y ofrece abrir Ajustes.
- [ ] Al activar se registra `sessionStart`. Las fotos anteriores a la sesión no se cuentan.
- [ ] Una foto nueva de la Cámara aparece en «Fotos detectadas». Las capturas de pantalla no.
- [ ] Una imagen guardada desde Safari o WhatsApp se omite (heurística EXIF).

## Fase B: App Intent y automatización
- [ ] «Procesar fotos pendientes» aparece en Atajos.
- [ ] La automatización Cámara → Se cierra → Ejecutar inmediatamente lanza el intent **sin abrir la app**.
- [ ] Con el interruptor apagado, el intent responde «Modo automático desactivado» y no envía nada.
- [ ] Medir el tiempo real que iOS concede al intent con 1, 3 y 6 fotos (preparación JPEG + Vision).
- [ ] La subida continúa tras salir del intent (URLSession en segundo plano) y el servidor recibe el trabajo una sola vez.

## Fase C: imagen de prueba en Favoritos
- [ ] Prueba de funcionamiento → «Guardar imagen de prueba como Favorita (local)» en verde.
- [ ] La imagen aparece en Fotos → Favoritos y en el álbum «AutoGPT Watch».
- [ ] La imagen llega al Apple Watch (anota cuánto tarda).

## Fase D: backend y OpenAI reales
- [ ] `OPENAI_MODEL` verificado en la documentación vigente. Una foto real de un ejercicio produce una respuesta correcta.
- [ ] Una foto sin ejercicios produce «Sin ejercicios detectados» y no se guarda ninguna imagen.
- [ ] Coste y latencia por trabajo anotados.

## Fase E: renderizado y visuales
- [ ] Respuesta larga dividida en páginas legibles en el reloj (con zoom de la Digital Crown).
- [ ] Fórmulas, tablas y código se leen bien en el formato «watch».
- [ ] Una pregunta de autómata o grafo genera la imagen Graphviz; una de función genera la gráfica.
- [ ] Con «Permitir ilustraciones» desactivado no se llama a la Images API.

## Fase F: robustez
- [ ] Modo avión durante la subida: el trabajo pasa a «Reintentando» y se completa al volver la red.
- [ ] Forzar el cierre de la app con un trabajo en curso: al reabrirla, se recupera sin duplicar fotos ni respuestas.
- [ ] Push silenciosa (cuenta de pago): guarda sin abrir la app. Anota la fiabilidad observada.
- [ ] Sin push: el resultado se guarda al volver a cerrar la Cámara o al abrir la app.
- [ ] Aviso «toca para guardar» tras 2 minutos sin confirmar.
- [ ] iPhone bloqueado al llegar la push: comprobar si PhotoKit y el Llavero permiten guardar, o si queda para después.
- [ ] Borrar y reinstalar la app: los resultados pendientes en el servidor se recuperan («adopción»).
- [ ] Historial y contadores correctos tras varios ciclos.
