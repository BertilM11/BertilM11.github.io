# Política de seguridad

Sitio personal de Bertil Raxon (https://bertilm11.github.io) y sus programas, como Casino del Caos.

## Cómo avisar de un problema

No publiques los detalles en un issue abierto. Usa **Security › Report a vulnerability** en este
repositorio. Si esa opción no aparece, abre un issue que diga solo «Problema de seguridad: necesito un
canal privado».

## Cómo está protegido

- Sitio estático en GitHub Pages, solo por HTTPS.
- Casino del Caos: solo la cuenta de administrador puede leer y cambiar los datos en la nube
  (inicio de sesión con Google y reglas de Firestore que rechazan todo lo demás). La configuración web
  de Firebase que está en el código es pública por diseño: no da acceso a los datos.
- Los textos que se escriben (nombres de equipos) se escapan antes de mostrarse.
- El código se revisa con CodeQL en cada cambio y cada lunes; GitHub bloquea la subida de secretos.
