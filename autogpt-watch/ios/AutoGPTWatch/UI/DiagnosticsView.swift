import Photos
import SwiftUI
import UIKit
import UserNotifications
import AutoGPTCore

/// "Prueba de funcionamiento": comprueba permisos, servidor y el guardado real en Favoritos.
struct DiagnosticsView: View {
    @EnvironmentObject private var settings: SettingsStore
    @Environment(\.dismiss) private var dismiss

    enum CheckState { case pending, running, ok, warning, failed }

    struct Check: Identifiable {
        let id: Int
        let title: String
        var state: CheckState = .pending
        var detail = ""
    }

    @State private var checks: [Check] = [
        Check(id: 0, title: "Acceso completo a Fotos"),
        Check(id: 1, title: "Notificaciones"),
        Check(id: 2, title: "Actualización en segundo plano"),
        Check(id: 3, title: "Servidor accesible"),
        Check(id: 4, title: "Token del dispositivo"),
        Check(id: 5, title: "Notificaciones push del servidor"),
        Check(id: 6, title: "Guardar imagen de prueba como Favorita (local)"),
        Check(id: 7, title: "Renderizado en servidor → descarga → Favoritos"),
    ]
    @State private var running = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(checks) { check in
                        HStack(alignment: .top, spacing: 12) {
                            icon(for: check.state).frame(width: 24)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(check.title).font(.subheadline.weight(.semibold))
                                if !check.detail.isEmpty {
                                    Text(check.detail).font(.caption).foregroundStyle(Theme.secondaryText)
                                }
                            }
                        }
                        .padding(.vertical, 2)
                    }
                } footer: {
                    Text("Las pruebas 7 y 8 guardan imágenes marcadas como PRUEBA en Fotos (Favoritos). Puedes borrarlas después. Ninguna prueba usa IA ni simula respuestas.")
                }
                Section {
                    Button {
                        Task { await runAll() }
                    } label: {
                        HStack {
                            Text(running ? "Ejecutando…" : "Ejecutar prueba de funcionamiento")
                            Spacer()
                            if running { ProgressView() }
                        }
                    }
                    .disabled(running)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Prueba de funcionamiento")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Cerrar") { dismiss() } }
            }
        }
    }

    @ViewBuilder
    private func icon(for state: CheckState) -> some View {
        switch state {
        case .pending: Image(systemName: "circle").foregroundStyle(.gray)
        case .running: ProgressView()
        case .ok: Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.accent)
        case .warning: Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Theme.warning)
        case .failed: Image(systemName: "xmark.octagon.fill").foregroundStyle(Theme.danger)
        }
    }

    private func set(_ id: Int, _ state: CheckState, _ detail: String = "") {
        checks[id].state = state
        checks[id].detail = detail
    }

    private func runAll() async {
        running = true
        defer { running = false }
        for i in checks.indices { set(i, .pending) }
        let services = AppServices.shared

        // 0. Fotos
        set(0, .running)
        if PhotoLibraryService.authorizationStatus == .notDetermined {
            _ = await PhotoLibraryService.requestAccess()
        }
        switch PhotoLibraryService.authorizationStatus {
        case .authorized: set(0, .ok, "Acceso completo concedido.")
        case .limited: set(0, .failed, "Acceso limitado. Ajustes → AutoGPT Watch → Fotos → Acceso completo.")
        default: set(0, .failed, "Sin acceso. Ajustes → AutoGPT Watch → Fotos → Acceso completo.")
        }

        // 1. Notificaciones
        set(1, .running)
        var notif = await services.notifications.authorizationStatus()
        if notif == .notDetermined {
            await services.notifications.requestAuthorization()
            notif = await services.notifications.authorizationStatus()
        }
        set(1, notif == .authorized ? .ok : .warning,
            notif == .authorized ? "Permitidas." : "Desactivadas: no se avisará si hace falta abrir la app para terminar un guardado.")

        // 2. Background refresh
        let bg = UIApplication.shared.backgroundRefreshStatus
        set(2, bg == .available ? .ok : .warning,
            bg == .available ? "Disponible (iOS decide cuándo se ejecuta)." : "Desactivada en Ajustes o por Modo de bajo consumo.")

        // 3-4. Servidor
        guard let config = settings.serverConfiguration else {
            set(3, .failed, "Configura la URL (https) y el token.")
            set(4, .failed)
            set(5, .failed)
            set(7, .failed)
            await runLocalSave(services)
            return
        }
        let api = APIClient(config: config)
        set(3, .running)
        var health: ServerHealth?
        do {
            health = try await api.health()
            set(3, health!.aiConfigured ? .ok : .warning,
                "Versión \(health!.version)." + (health!.aiConfigured ? " IA configurada." : " ⚠️ Falta configurar OPENAI_API_KEY/OPENAI_MODEL."))
        } catch {
            set(3, .failed, error.localizedDescription)
        }
        set(4, .running)
        do {
            let me = try await api.me()
            set(4, .ok, "Válido. Hoy: \(me.usageToday.jobs) trabajos, \(me.usageToday.images) imágenes.")
        } catch {
            set(4, .failed, error.localizedDescription)
        }

        // 5. Push
        if let health, health.apnsEnabled, settings.apnsToken != nil {
            set(5, .ok, "Registrado. Aun así, iOS puede retrasar o descartar las push silenciosas.")
        } else if health?.apnsEnabled == false {
            set(5, .warning, "El servidor no tiene APNs configurado: los resultados se guardarán en la siguiente ejecución del Atajo, al abrir la app o en el refresco en segundo plano.")
        } else {
            set(5, .warning, "Este iPhone no tiene token push (requiere cuenta de desarrollador de pago y el entitlement de notificaciones).")
        }

        // 6. Guardado local (Fase C)
        await runLocalSave(services)

        // 7. Renderizado en servidor + descarga + guardado
        set(7, .running, "Esperando al servidor…")
        do {
            let count = try await services.coordinator.runServerSelfTest()
            set(7, .ok, "\(count) imagen(es) de PRUEBA descargadas y guardadas como Favoritas.")
        } catch {
            set(7, .failed, error.localizedDescription)
        }
    }

    private func runLocalSave(_ services: AppServices) async {
        set(6, .running)
        do {
            _ = try await services.coordinator.saveLocalTestImage()
            set(6, .ok, "Guardada y verificada como Favorita.")
        } catch {
            set(6, .failed, error.localizedDescription)
        }
    }
}
