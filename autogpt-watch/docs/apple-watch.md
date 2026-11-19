# Ver las respuestas en el Apple Watch

AutoGPT Watch no tiene app para watchOS. Usa la app **Fotos** del reloj, que sincroniza un álbum del iPhone.

## Configuración (una vez)
1. En el iPhone, abre la app **Watch** → pestaña **Mi reloj** → **Fotos**.
2. **Álbum sincronizado** → **Favoritas**.
3. **Límite de fotos** → un valor holgado (100, 250 o 500), porque cada respuesta puede ocupar varias imágenes.
4. Opcional: desactiva **Recuerdos** y **Fotos destacadas** para que en el reloj aparezcan sólo tus Favoritas.

## Cómo se ven
- Con el formato **Apple Watch** (Configuración → Respuestas), cada imagen mide 792×968 px (proporción 4:5), con letra grande y cabecera «n/N».
- Las respuestas largas se dividen en varias imágenes numeradas, que se guardan en orden (`creationDate` creciente).
- Los diagramas, gráficas e ilustraciones se guardan como imágenes aparte («Imagen k/M»).
- En el reloj, gira la **Digital Crown** para ampliar.

## Limitaciones
- watchOS decide cuándo sincroniza: suele hacerlo con el reloj cerca del iPhone y, a menudo, mientras carga. **No hay forma de forzarlo desde una app.** Puede tardar desde un par de minutos hasta más.
- Si se supera el límite de fotos, el reloj muestra sólo las Favoritas más recientes que caben.
- Para liberar espacio, quita de Favoritos (o borra) las respuestas antiguas en el iPhone. El álbum «AutoGPT Watch» las agrupa para encontrarlas fácilmente.
