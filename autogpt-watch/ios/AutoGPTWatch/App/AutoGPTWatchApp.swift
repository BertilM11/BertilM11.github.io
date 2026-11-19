import SwiftData
import SwiftUI

@main
struct AutoGPTWatchApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase

    private let services = AppServices.shared

    var body: some Scene {
        WindowGroup {
            MainView()
                .environmentObject(services.settings)
                .environmentObject(services.coordinator)
                .preferredColorScheme(.dark)
                .tint(Theme.accent)
        }
        .modelContainer(services.container)
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active:
                Task { await services.coordinator.onForeground() }
            case .background:
                if services.coordinator.hasPendingWork {
                    BackgroundRefresh.schedule()
                }
            default:
                break
            }
        }
    }
}
