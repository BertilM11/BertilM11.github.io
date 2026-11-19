# Compilar e instalar en un iPhone físico

## Requisitos
- Mac con **Xcode 16 o posterior**. El proyecto usa carpetas sincronizadas (`objectVersion 77`).
- iPhone con **iOS 17 o posterior** (SwiftData, App Intents con `AppShortcut` y `onChange` de dos parámetros).
- Cuenta de Apple:
  - **De pago** (99 USD/año): permite push y la firma dura un año.
  - **Gratuita (Personal Team)**: la app caduca a los 7 días y **no hay push**. Usa `Config/AutoGPTWatch-NoPush.entitlements`.

## Pasos
1. Abre `ios/AutoGPTWatch.xcodeproj`. Xcode resolverá el paquete local `Packages/AutoGPTCore`.
   - Si Xcode no abre el proyecto, regenéralo con `python3 ios/tools/generate_xcodeproj.py`, o con `brew install xcodegen && cd ios && xcodegen generate`.
2. Selecciona el target **AutoGPTWatch** y ve a **Signing & Capabilities**:
   - En **Team**, elige tu equipo.
   - Cambia el **Bundle Identifier** (`com.example.autogptwatch`) por uno propio. Usa el mismo valor en `APNS_BUNDLE_ID` del servidor.
   - Con cuenta de pago, comprueba que aparecen **Push Notifications** y **Background Modes** (*Background fetch* y *Remote notifications*). El proyecto ya los declara en `Config/AutoGPTWatch.entitlements` y `Config/Info.plist`.
   - Con cuenta gratuita, ve a Build Settings → *Code Signing Entitlements* y pon `Config/AutoGPTWatch-NoPush.entitlements`.
3. Conecta el iPhone. Ve a **Ajustes → Privacidad y seguridad → Modo desarrollador** y actívalo (iOS lo pide la primera vez).
4. Elige tu iPhone como destino y pulsa **Run (⌘R)**. Si iOS dice que el desarrollador no es de confianza, ve a Ajustes → General → VPN y gestión de dispositivos → confía en tu certificado.

## Primera ejecución
1. Abre **Configuración** (engranaje): URL `https://…` de tu servidor y el token del dispositivo. Pulsa **Guardar y probar conexión**.
2. Abre **Prueba de funcionamiento** (sello) y ejecútala. Debe quedar en verde:
   - Fotos (acceso **completo**, no limitado);
   - Servidor y Token;
   - **Guardar imagen de prueba como Favorita (local)**, que corresponde a la Fase C;
   - **Renderizado en servidor → descarga → Favoritos**.
3. Pulsa el interruptor grande. Primero se pide el consentimiento, después el acceso a Fotos y a notificaciones.
4. Configura la automatización: [shortcuts-automation.md](shortcuts-automation.md).

## Pruebas de la lógica (XCTest)
```bash
cd ios/Packages/AutoGPTCore
swift test
```
También puedes usar ⌘U en Xcode con el esquema AutoGPTWatch, que incluye `AutoGPTCoreTests`.

## Depuración
- Los registros aparecen en **Consola.app** filtrando por el subsistema del bundle id.
- Para probar la push silenciosa sin servidor, arrastra un `.apns` al simulador. En un dispositivo real, usa el servidor con APNs configurado.
- Para forzar el refresco en segundo plano mientras depuras, pausa la app y ejecuta en LLDB:
  `e -l objc -- (void)[[BGTaskScheduler sharedScheduler] _simulateLaunchForTaskWithIdentifier:@"<bundle id>.refresh"]`
