import Photos
import SwiftUI
import UIKit
import UserNotifications
import AutoGPTCore

struct SettingsView: View {
    @EnvironmentObject private var settings: SettingsStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    @State private var serverInput = ""
    @State private var tokenInput = ""
    @State private var connectionResult: String?
    @State private var connectionOK = false
    @State private var testing = false
    @State private var notificationStatus: UNAuthorizationStatus = .notDetermined
    @State private var showConsent = false

    var body: some View {
        NavigationStack {
            Form {
                serverSection
                responseSection
                detectionSection
                photosSection
                privacySection
                Section("Automatización") {
                    NavigationLink("Guía: automatización al cerrar la Cámara") { AutomationGuideView() }
                    NavigationLink("Guía: Favoritos en el Apple Watch") { WatchGuideView() }
                }
                permissionsSection
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Configuración")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Listo") { dismiss() } }
            }
            .task {
                serverInput = settings.serverURL
                notificationStatus = await AppServices.shared.notifications.authorizationStatus()
            }
            .sheet(isPresented: $showConsent) {
                ConsentView { accepted in
                    showConsent = false
                    if accepted { settings.consentGivenAt = Date() }
                }
            }
        }
    }

    // MARK: Secciones

    private var serverSection: some View {
        Section {
            TextField("https://api.tudominio.com", text: $serverInput)
                .keyboardType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            SecureField(settings.hasServerToken ? "Token guardado (escribe para cambiarlo)" : "Token del dispositivo", text: $tokenInput)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button {
                Task { await saveAndTest() }
            } label: {
                HStack {
                    Text("Guardar y probar conexión")
                    Spacer()
                    if testing { ProgressView() }
                }
            }
            .disabled(testing || serverInput.isEmpty)
            if let connectionResult {
                Label(connectionResult, systemImage: connectionOK ? "checkmark.circle.fill" : "xmark.octagon.fill")
                    .foregroundStyle(connectionOK ? Theme.accent : Theme.danger)
                    .font(.footnote)
            }
        } header: {
            Text("Servidor")
        } footer: {
            Text("La clave de OpenAI vive sólo en tu servidor. Aquí se guarda únicamente el token del dispositivo, en el Llavero del iPhone.")
        }
    }

    private var responseSection: some View {
        Section {
            Picker("Formato", selection: $settings.preset) {
                ForEach(ResponsePreset.allCases) { Text($0.displayName).tag($0) }
            }
            Picker("Idioma", selection: $settings.language) {
                ForEach(ResponseLanguage.allCases) { Text($0.displayName).tag($0) }
            }
            Toggle("Permitir ilustraciones generadas por IA", isOn: $settings.allowIllustrations)
        } header: {
            Text("Respuestas e imágenes")
        } footer: {
            Text("Diagramas, autómatas, circuitos y gráficas se dibujan siempre con herramientas deterministas. Las ilustraciones por IA sólo se crean si la pregunta pide un dibujo o diseño libre.")
        }
    }

    private var detectionSection: some View {
        Section {
            Toggle("Sólo fotos de la Cámara del iPhone", isOn: $settings.requireCameraMetadata)
            Toggle("Filtrar con Vision (texto detectado)", isOn: $settings.visionFilterEnabled)
            if settings.visionFilterEnabled {
                Stepper("Mínimo \(settings.visionMinCharacters) caracteres", value: $settings.visionMinCharacters, in: 5 ... 200, step: 5)
            }
        } header: {
            Text("Detección")
        } footer: {
            Text("Las capturas de pantalla, las imágenes guardadas desde otras apps y los resultados de AutoGPT Watch nunca se envían. Las fotos sin texto suficiente se omiten.")
        }
    }

    private var photosSection: some View {
        Section {
            Toggle("Añadir también al álbum «\(SettingsStore.albumName)»", isOn: $settings.createAlbum)
            Toggle("Avisar cuando se guarden respuestas", isOn: $settings.notifyOnSave)
        } header: {
            Text("Fotos")
        } footer: {
            Text("Todas las respuestas se guardan como Favoritas. Las fotos originales nunca se modifican ni se borran.")
        }
    }

    private var privacySection: some View {
        Section("Privacidad") {
            Toggle("Borrar las fotos del servidor tras procesarlas", isOn: $settings.deleteUploads)
            if let date = settings.consentGivenAt {
                LabeledContent("Consentimiento", value: date.formatted(date: .abbreviated, time: .shortened))
                Button("Retirar consentimiento", role: .destructive) {
                    settings.consentGivenAt = nil
                    AppServices.shared.coordinator.setAutoMode(false)
                }
            } else {
                Button("Revisar y aceptar el envío de fotos") { showConsent = true }
            }
        }
    }

    private var permissionsSection: some View {
        Section("Permisos") {
            permissionRow("Fotos (acceso completo)", ok: PhotoLibraryService.hasFullAccess)
            permissionRow("Notificaciones", ok: notificationStatus == .authorized || notificationStatus == .provisional)
            permissionRow("Actualización en segundo plano",
                          ok: UIApplication.shared.backgroundRefreshStatus == .available)
            Button("Abrir Ajustes de iOS") {
                if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
            }
        }
    }

    private func permissionRow(_ title: String, ok: Bool) -> some View {
        HStack {
            Text(title)
            Spacer()
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(ok ? Theme.accent : Theme.warning)
        }
    }

    // MARK: Acciones

    private func saveAndTest() async {
        testing = true
        defer { testing = false }
        do {
            _ = try ServerConfiguration.normalizedBaseURL(serverInput)
        } catch {
            connectionOK = false
            connectionResult = APIError.invalidServerURL.localizedDescription
            return
        }
        settings.serverURL = serverInput.trimmingCharacters(in: .whitespacesAndNewlines)
        if !tokenInput.isEmpty {
            settings.setServerToken(tokenInput)
            tokenInput = ""
        }
        guard let config = settings.serverConfiguration else {
            connectionOK = false
            connectionResult = APIError.notConfigured.localizedDescription
            return
        }
        let api = APIClient(config: config)
        do {
            let health = try await api.health()
            let me = try await api.me()
            connectionOK = health.aiConfigured
            var text = "Conectado (v\(health.version)). Hoy: \(me.usageToday.jobs)/\(me.limits.maxJobsPerDay) trabajos."
            if !health.aiConfigured { text += " ⚠️ El servidor no tiene configurada la IA." }
            if !health.apnsEnabled { text += " Push desactivadas en el servidor." }
            connectionResult = text
            if let token = settings.apnsToken {
                await AppServices.shared.coordinator.registerPushToken(token)
            }
        } catch {
            connectionOK = false
            connectionResult = error.localizedDescription
        }
    }
}
