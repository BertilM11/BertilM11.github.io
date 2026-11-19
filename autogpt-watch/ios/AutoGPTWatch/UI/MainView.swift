import Photos
import SwiftData
import SwiftUI
import UIKit
import AutoGPTCore

struct MainView: View {
    @EnvironmentObject private var settings: SettingsStore
    @EnvironmentObject private var coordinator: ProcessingCoordinator
    @Environment(\.openURL) private var openURL
    @Environment(\.scenePhase) private var scenePhase

    @Query(sort: \LocalJob.createdAt, order: .reverse) private var jobs: [LocalJob]
    @Query private var processedAssets: [ProcessedAsset]

    @State private var showSettings = false
    @State private var showDiagnostics = false
    @State private var showConsent = false
    @State private var showGuide = false
    @State private var photoStatus = PhotoLibraryService.authorizationStatus
    @State private var localMessage: String?

    // MARK: Datos derivados

    private var pendingJobs: [LocalJob] { jobs.filter { $0.phase.isPending || $0.phase == .failed } }
    private var historyJobs: [LocalJob] { Array(jobs.filter { $0.phase.isTerminal }.prefix(30)) }

    private var detectedCount: Int {
        guard let start = settings.sessionStart else { return 0 }
        return processedAssets.filter { $0.processedAt >= start }.count
    }

    private var savedCount: Int {
        guard let start = settings.sessionStart else { return 0 }
        return jobs.filter { $0.phase == .saved && !$0.isSelfTest && $0.createdAt >= start }.count
    }

    private var issues: [SetupIssue] {
        var list: [SetupIssue] = []
        if let warning = AppServices.shared.storageWarning {
            list.append(SetupIssue(id: "storage", icon: "externaldrive.badge.exclamationmark", text: warning, action: nil, actionTitle: nil))
        }
        if !settings.consentGiven {
            list.append(SetupIssue(id: "consent", icon: "hand.raised", text: "Acepta el envío de fotos al servicio de IA.",
                                   action: { showConsent = true }, actionTitle: "Revisar"))
        }
        if photoStatus != .authorized {
            let text = photoStatus == .limited
                ? "Acceso limitado a Fotos: se necesita acceso completo para detectar fotos nuevas y marcar Favoritos."
                : "AutoGPT Watch necesita acceso completo a Fotos."
            list.append(SetupIssue(id: "photos", icon: "photo.on.rectangle", text: text,
                                   action: { Task { await fixPhotoAccess() } },
                                   actionTitle: photoStatus == .notDetermined ? "Permitir" : "Abrir Ajustes"))
        }
        if settings.serverConfiguration == nil {
            list.append(SetupIssue(id: "server", icon: "server.rack", text: "Configura la URL del servidor y el token del dispositivo.",
                                   action: { showSettings = true }, actionTitle: "Configurar"))
        }
        return list
    }

    private var status: AppStatus {
        if jobs.contains(where: { $0.phase == .failed }) || (settings.autoModeEnabled && !issues.isEmpty) { return .error }
        if coordinator.isBusy || jobs.contains(where: { $0.phase.isPending }) { return .processing }
        return settings.autoModeEnabled ? .active : .inactive
    }

    // MARK: Vista

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 22) {
                    header
                    VStack(spacing: 16) {
                        PowerToggle(isOn: settings.autoModeEnabled) { toggleTapped() }
                        StatusPill(status: status)
                        if let message = localMessage ?? coordinator.lastMessage {
                            Text(message)
                                .font(.footnote)
                                .multilineTextAlignment(.center)
                                .foregroundStyle(Theme.secondaryText)
                                .padding(.horizontal, 12)
                        }
                    }
                    .padding(.vertical, 8)

                    if !issues.isEmpty { issuesSection }

                    HStack(spacing: 10) {
                        StatCard(value: detectedCount, label: "Fotos detectadas", systemImage: "camera.viewfinder")
                        StatCard(value: savedCount, label: "Respuestas guardadas", systemImage: "heart.fill")
                        StatCard(value: pendingJobs.filter { $0.phase.isPending }.count, label: "Trabajos pendientes",
                                 systemImage: "hourglass")
                    }

                    if !pendingJobs.isEmpty { pendingSection }
                    historySection
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 40)
            }
            .scrollIndicators(.hidden)
            .background(Theme.background.ignoresSafeArea())
            .refreshable { await coordinator.syncNow() }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showDiagnostics = true } label: {
                        Label("Prueba de funcionamiento", systemImage: "checkmark.seal")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: {
                        Label("Configuración", systemImage: "gearshape")
                    }
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .sheet(isPresented: $showDiagnostics) { DiagnosticsView() }
            .sheet(isPresented: $showGuide) { NavigationStack { AutomationGuideView() } }
            .sheet(isPresented: $showConsent) {
                ConsentView { accepted in
                    showConsent = false
                    if accepted {
                        settings.consentGivenAt = Date()
                        toggleTapped()
                    }
                }
                .interactiveDismissDisabled()
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { photoStatus = PhotoLibraryService.authorizationStatus }
            }
        }
    }

    private var header: some View {
        VStack(spacing: 6) {
            Text("AutoGPT Watch")
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .foregroundStyle(LinearGradient(colors: [.white, Color.white.opacity(0.7)], startPoint: .top, endPoint: .bottom))
            Text("Fotos de la Cámara → respuestas en Favoritos del Apple Watch")
                .font(.footnote)
                .foregroundStyle(Theme.secondaryText)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 8)
    }

    private var issuesSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader("Requiere atención")
            ForEach(issues) { issue in
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: issue.icon)
                        .font(.system(size: 18))
                        .foregroundStyle(Theme.warning)
                        .frame(width: 24)
                    VStack(alignment: .leading, spacing: 8) {
                        Text(issue.text).font(.subheadline)
                        if let action = issue.action, let title = issue.actionTitle {
                            Button(title, action: action)
                                .buttonStyle(.borderedProminent)
                                .controlSize(.small)
                        }
                    }
                }
                .card()
            }
        }
    }

    private var pendingSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader("Trabajos pendientes", trailing: AnyView(
                Button {
                    Task { await coordinator.syncNow() }
                } label: {
                    Label("Sincronizar", systemImage: "arrow.triangle.2.circlepath")
                        .font(.caption.weight(.semibold))
                }
                .disabled(coordinator.isBusy)
            ))
            ForEach(pendingJobs) { job in
                JobRow(
                    job: job,
                    onRetry: job.phase == .failed || job.phase == .retryWait ? { Task { await coordinator.retry(job) } } : nil,
                    onDiscard: job.phase == .failed ? { coordinator.discard(job) } : nil
                )
            }
        }
    }

    private var historySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader("Historial", trailing: AnyView(
                Button { showGuide = true } label: {
                    Label("Guía de Atajos", systemImage: "questionmark.circle").font(.caption.weight(.semibold))
                }
            ))
            if historyJobs.isEmpty {
                Text("Aún no hay resultados. Activa el modo automático y toma una foto de un ejercicio con la Cámara.")
                    .font(.subheadline)
                    .foregroundStyle(Theme.secondaryText)
                    .card()
            } else {
                ForEach(historyJobs) { job in
                    JobRow(job: job)
                }
            }
        }
    }

    // MARK: Acciones

    private func toggleTapped() {
        if settings.autoModeEnabled {
            coordinator.setAutoMode(false)
            localMessage = nil
            return
        }
        Task {
            guard settings.consentGiven else {
                showConsent = true
                return
            }
            if PhotoLibraryService.authorizationStatus == .notDetermined {
                _ = await PhotoLibraryService.requestAccess()
            }
            photoStatus = PhotoLibraryService.authorizationStatus
            guard PhotoLibraryService.hasFullAccess else {
                localMessage = "Concede acceso completo a Fotos para activar el modo automático."
                return
            }
            guard settings.serverConfiguration != nil else {
                localMessage = "Configura el servidor antes de activar el modo automático."
                showSettings = true
                return
            }
            await AppServices.shared.notifications.requestAuthorization()
            localMessage = nil
            coordinator.setAutoMode(true)
        }
    }

    private func fixPhotoAccess() async {
        if PhotoLibraryService.authorizationStatus == .notDetermined {
            _ = await PhotoLibraryService.requestAccess()
            photoStatus = PhotoLibraryService.authorizationStatus
        } else if let url = URL(string: UIApplication.openSettingsURLString) {
            openURL(url)
        }
    }
}

struct SetupIssue: Identifiable {
    let id: String
    let icon: String
    let text: String
    let action: (() -> Void)?
    let actionTitle: String?
}
