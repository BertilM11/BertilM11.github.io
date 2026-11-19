import AppIntents
import Foundation

/// Acción principal para la automatización personal de Atajos:
/// App → Cámara → «Se cierra» → Ejecutar inmediatamente → «Procesar fotos pendientes».
/// Siempre respeta el interruptor principal de la app.
struct ProcessPendingPhotosIntent: AppIntent {
    static var title: LocalizedStringResource = "Procesar fotos pendientes"
    static var description = IntentDescription(
        "Detecta las fotos nuevas tomadas con la Cámara durante la sesión activa, las envía a analizar y guarda en Fotos, como Favoritas, las respuestas que ya estén listas."
    )
    /// Se ejecuta en segundo plano sin abrir la app.
    static var openAppWhenRun: Bool = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        // iOS concede un tiempo limitado a los intents en segundo plano: se envían las
        // fotos (la subida continúa en una URLSession en segundo plano) y se recogen los
        // resultados que ya estén listos; el resto llega por push, refresco o la próxima ejecución.
        let summary = await AppServices.shared.coordinator.processPendingPhotos(deadline: Date().addingTimeInterval(20))
        return .result(dialog: "\(summary.message)")
    }
}

/// Recupera y guarda en Fotos los resultados ya procesados por el servidor.
/// Útil como segundo paso en el Atajo (tras «Esperar») o para lanzarlo a mano.
struct SyncResultsIntent: AppIntent {
    static var title: LocalizedStringResource = "Guardar respuestas listas"
    static var description = IntentDescription(
        "Descarga las respuestas que el servidor ya terminó y las guarda en Fotos como Favoritas para el Apple Watch."
    )
    static var openAppWhenRun: Bool = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let coordinator = AppServices.shared.coordinator
        let saved = await coordinator.syncResults(deadline: Date().addingTimeInterval(25))
        let pending = coordinator.hasPendingWork
        let message: String
        if saved > 0 {
            message = "Guardadas en Favoritos las respuestas de \(saved) trabajo(s)."
        } else if pending {
            message = "Aún hay trabajos en proceso. Se guardarán automáticamente al terminar."
        } else {
            message = "No hay respuestas pendientes."
        }
        return .result(dialog: "\(message)")
    }
}

/// Permite activar o desactivar el modo automático desde Atajos.
struct SetAutoModeIntent: AppIntent {
    static var title: LocalizedStringResource = "Activar o desactivar AutoGPT Watch"
    static var description = IntentDescription("Inicia o detiene la sesión de detección automática de fotos.")
    static var openAppWhenRun: Bool = false

    @Parameter(title: "Activado", default: true)
    var enabled: Bool

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let services = AppServices.shared
        if enabled {
            guard services.settings.consentGiven else {
                return .result(dialog: "Abre AutoGPT Watch para aceptar el envío de fotos al servicio de IA.")
            }
            guard PhotoLibraryService.hasFullAccess else {
                return .result(dialog: "Abre AutoGPT Watch para conceder acceso completo a Fotos.")
            }
        }
        services.coordinator.setAutoMode(enabled)
        let message = enabled ? "Modo automático activado." : "Modo automático desactivado."
        return .result(dialog: "\(message)")
    }
}

struct AutoGPTWatchShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: ProcessPendingPhotosIntent(),
            phrases: ["Procesar fotos con \(.applicationName)"],
            shortTitle: "Procesar fotos",
            systemImageName: "sparkles"
        )
        AppShortcut(
            intent: SyncResultsIntent(),
            phrases: ["Guardar respuestas de \(.applicationName)"],
            shortTitle: "Guardar respuestas",
            systemImageName: "square.and.arrow.down"
        )
    }
}
