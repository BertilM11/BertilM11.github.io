# Automatización en Atajos: «al cerrar la Cámara»

La app expone tres acciones en Atajos:

| Acción | Qué hace |
|---|---|
| **Procesar fotos pendientes** (`ProcessPendingPhotosIntent`) | Detecta las fotos nuevas de la sesión, filtra con Vision, las envía y guarda lo que ya esté listo |
| **Guardar respuestas listas** (`SyncResultsIntent`) | Sólo descarga y guarda resultados terminados |
| **Activar o desactivar AutoGPT Watch** (`SetAutoModeIntent`) | Cambia el interruptor principal |

Las tres se ejecutan **sin abrir la app** y respetan el interruptor: con el modo automático apagado, «Procesar fotos pendientes» termina sin hacer nada.

## Crear la automatización
1. Abre la app **Atajos** y ve a la pestaña **Automatización**.
2. Toca **+** (o **Nueva automatización**).
3. Elige **App**.
4. En **App**, toca *Elegir* y selecciona **Cámara**.
5. Marca **Se cierra** y desmarca **Se abre**.
6. Selecciona **Ejecutar inmediatamente**. Opcionalmente desactiva **Notificar al ejecutar**.
7. Toca **Siguiente** y luego **Nueva acción en blanco** (o **Añadir acción**).
8. Busca **AutoGPT Watch** y añade **Procesar fotos pendientes**.
9. *(Opcional)* Para intentar recoger el resultado en la misma ejecución, añade **Esperar** con 60 segundos y luego **Guardar respuestas listas**. iOS puede interrumpir esperas largas; si ocurre, el resultado llega por las otras vías.
10. Toca **OK** o **Listo**.

> Los nombres exactos de los menús pueden variar entre versiones de iOS. La automatización «App → Se cierra» y la opción «Ejecutar inmediatamente» existen desde iOS 17.

## Uso diario
1. Abre AutoGPT Watch y pulsa el interruptor. Empieza una **sesión**: sólo cuentan las fotos tomadas a partir de ese momento.
2. Toma una o varias fotos con la **Cámara** de iOS.
3. Sal de la Cámara. La automatización envía las fotos en unos segundos y muestra un aviso con el resumen.
4. Cuando el servidor termina (normalmente entre 20 s y 2 min), las respuestas se guardan en **Favoritos** por una de estas vías:
   - llega la push silenciosa;
   - vuelves a cerrar la Cámara;
   - abres la app;
   - iOS ejecuta el refresco en segundo plano;
   - tocas el aviso «toca para guardar», que llega si el guardado no se confirmó en 2 minutos.
5. Al terminar, apaga el interruptor.

## Qué se envía y qué no
- Sólo fotos **posteriores** al inicio de la sesión.
- Se excluyen capturas de pantalla, PNG, resultados propios, fotos ya procesadas y, con la opción activa, imágenes sin metadatos de cámara de iPhone.
- Vision descarta en el iPhone las fotos con menos de N caracteres de texto (configurable).
- Las fotos se envían reducidas a 2048 px y **sin EXIF ni ubicación**.
