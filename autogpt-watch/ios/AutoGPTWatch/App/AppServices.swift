import Foundation
import SwiftData

/// Contenedor de dependencias compartido por la UI, los App Intents, el AppDelegate y
/// las tareas en segundo plano (todos se ejecutan en el mismo proceso de la app).
@MainActor
final class AppServices {
    static let shared = AppServices()

    let container: ModelContainer
    let settings: SettingsStore
    let store: JobStore
    let photos: PhotoLibraryService
    let notifications: NotificationManager
    let coordinator: ProcessingCoordinator
    /// Si la base de datos no se pudo abrir se usa una en memoria y se avisa en la UI.
    let storageWarning: String?

    private init() {
        var warning: String?
        let schema = Schema([LocalJob.self, ProcessedAsset.self, SavedResult.self])
        let container: ModelContainer
        do {
            container = try ModelContainer(for: schema, configurations: ModelConfiguration(schema: schema))
        } catch {
            warning = "No se pudo abrir el historial (\(error.localizedDescription)). Se usa uno temporal."
            // swiftlint:disable:next force_try
            container = try! ModelContainer(for: schema, configurations: ModelConfiguration(schema: schema, isStoredInMemoryOnly: true))
        }
        self.container = container
        storageWarning = warning
        settings = SettingsStore()
        store = JobStore(container: container)
        photos = PhotoLibraryService()
        notifications = NotificationManager()
        coordinator = ProcessingCoordinator(settings: settings, store: store, photos: photos, notifications: notifications)
    }
}
