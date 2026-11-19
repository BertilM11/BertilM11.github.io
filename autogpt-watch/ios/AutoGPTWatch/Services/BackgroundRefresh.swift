import BackgroundTasks
import Foundation

/// BGAppRefreshTask: iOS decide CUÁNDO se ejecuta (puede tardar horas o no ocurrir).
/// Es sólo un respaldo para recuperar resultados; no es el mecanismo principal.
enum BackgroundRefresh {
    static var identifier: String {
        (Bundle.main.bundleIdentifier ?? "AutoGPTWatch") + ".refresh"
    }

    /// Llamar en application(_:didFinishLaunchingWithOptions:), antes de que termine el arranque.
    static func register() {
        let ok = BGTaskScheduler.shared.register(forTaskWithIdentifier: identifier, using: nil) { task in
            guard let refresh = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            handle(refresh)
        }
        if !ok { AppLog.error("No se pudo registrar BGAppRefreshTask (revisa Info.plist)") }
    }

    static func schedule(after seconds: TimeInterval = 15 * 60) {
        let request = BGAppRefreshTaskRequest(identifier: identifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: seconds)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            AppLog.info("BGAppRefresh no programado: \(error.localizedDescription)")
        }
    }

    private static func handle(_ task: BGAppRefreshTask) {
        let work = Task { @MainActor in
            let services = AppServices.shared
            await services.coordinator.syncResults(deadline: Date().addingTimeInterval(25))
            if services.coordinator.hasPendingWork {
                schedule()
            }
            task.setTaskCompleted(success: true)
        }
        task.expirationHandler = {
            work.cancel()
        }
    }
}
