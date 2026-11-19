import Foundation
import UIKit
import UserNotifications

@MainActor
final class NotificationManager {
    nonisolated static let threadID = "autogpt-results"

    func authorizationStatus() async -> UNAuthorizationStatus {
        await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    @discardableResult
    func requestAuthorization() async -> Bool {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        if granted {
            UIApplication.shared.registerForRemoteNotifications()
        }
        return granted
    }

    /// Notificación local inmediata (sólo si el usuario la autorizó).
    func post(title: String, body: String, identifier: String = UUID().uuidString) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.threadIdentifier = Self.threadID
        let request = UNNotificationRequest(identifier: identifier, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request) { error in
            if let error { AppLog.error("Notificación: \(error.localizedDescription)") }
        }
    }

    /// Retira avisos de "toca para guardar" cuando el guardado ya se completó.
    func clearDelivered() {
        UNUserNotificationCenter.current().getDeliveredNotifications { notes in
            let ids = notes.filter { $0.request.content.threadIdentifier == Self.threadID
                && $0.request.content.userInfo["event"] as? String == "job_needs_save" }
                .map(\.request.identifier)
            UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: ids)
        }
    }
}
