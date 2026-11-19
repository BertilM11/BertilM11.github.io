import UIKit
import UserNotifications

final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        BackgroundTransferManager.shared.activate()
        BackgroundRefresh.register()
        UNUserNotificationCenter.current().delegate = self
        // Sólo obtiene el token si el usuario ya autorizó notificaciones o la app tiene
        // el entitlement de push; las notificaciones silenciosas no requieren permiso de alertas.
        application.registerForRemoteNotifications()
        return true
    }

    // MARK: URLSession en segundo plano

    func application(_ application: UIApplication, handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        guard identifier == BackgroundTransferManager.identifier else {
            completionHandler()
            return
        }
        BackgroundTransferManager.shared.setBackgroundCompletionHandler(completionHandler)
    }

    // MARK: Push (APNs)

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        Task { @MainActor in
            await AppServices.shared.coordinator.registerPushToken(hex)
        }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        AppLog.error("APNs no disponible: \(error.localizedDescription)")
    }

    /// Push silenciosa del servidor: iOS concede ~30 s para descargar y guardar.
    func application(_ application: UIApplication,
                     didReceiveRemoteNotification userInfo: [AnyHashable: Any],
                     fetchCompletionHandler completionHandler: @escaping (UIBackgroundFetchResult) -> Void) {
        Task { @MainActor in
            let result = await AppServices.shared.coordinator.handleRemoteNotification()
            completionHandler(result)
        }
    }

    // MARK: UNUserNotificationCenterDelegate

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        Task { @MainActor in
            await AppServices.shared.coordinator.syncNow()
            completionHandler()
        }
    }
}
