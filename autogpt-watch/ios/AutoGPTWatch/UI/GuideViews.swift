import SwiftUI

struct AutomationGuideView: View {
    @Environment(\.openURL) private var openURL

    private struct Step: Identifiable {
        let id: String
        let text: String
    }

    private let steps: [Step] = [
        Step(id: "1", text: "Abre la app Atajos y ve a la pestaña «Automatización»."),
        Step(id: "2", text: "Toca «+» (o «Nueva automatización») y elige «App»."),
        Step(id: "3", text: "En «App», selecciona «Cámara». Marca SOLO «Se cierra» y desmarca «Se abre»."),
        Step(id: "4", text: "Elige «Ejecutar inmediatamente» y desactiva «Notificar al ejecutar» si no quieres el aviso."),
        Step(id: "5", text: "Toca «Siguiente» → «Nueva acción en blanco» y busca «AutoGPT Watch»."),
        Step(id: "6", text: "Añade la acción «Procesar fotos pendientes»."),
        Step(id: "7", text: "Opcional: añade «Esperar» (60 s) y después «Guardar respuestas listas» para recoger el resultado en la misma ejecución. iOS puede interrumpir esperas largas."),
        Step(id: "8", text: "Listo. Activa el modo automático en AutoGPT Watch, toma fotos con la Cámara y sal de ella."),
    ]

    var body: some View {
        List {
            Section {
                ForEach(steps) { step in
                    HStack(alignment: .top, spacing: 12) {
                        Text(step.id)
                            .font(.system(size: 14, weight: .bold, design: .rounded))
                            .frame(width: 26, height: 26)
                            .background(Circle().fill(Theme.accent.opacity(0.2)))
                            .foregroundStyle(Theme.accent)
                        Text(step.text).font(.subheadline)
                    }
                    .padding(.vertical, 2)
                }
            } footer: {
                Text("La automatización respeta el interruptor de AutoGPT Watch: si está desactivado, la acción termina sin hacer nada. Los nombres de los menús pueden variar ligeramente según la versión de iOS.")
            }
            Section("Cómo llegan los resultados") {
                Text("El Atajo envía las fotos en segundos. El análisis tarda más (normalmente 20 s a 2 min) y continúa en tu servidor. Las respuestas se guardan en Favoritos cuando: llega la notificación push del servidor, vuelves a cerrar la Cámara, abres la app o iOS ejecuta el refresco en segundo plano. iOS no garantiza ejecución permanente en segundo plano.")
                    .font(.footnote)
            }
            Section {
                Button("Abrir Atajos") {
                    if let url = URL(string: "shortcuts://") { openURL(url) }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Automatización")
    }
}

struct WatchGuideView: View {
    var body: some View {
        List {
            Section("En el iPhone") {
                Text("1. Abre la app Watch → pestaña «Mi reloj» → «Fotos».")
                Text("2. En «Álbum sincronizado» elige «Favoritas».")
                Text("3. En «Límite de fotos» elige un valor suficiente (p. ej. 100 o más).")
                Text("4. Opcional: desactiva «Recuerdos» y «Fotos destacadas» para que sólo se sincronicen tus Favoritas.")
            }
            Section("Sincronización") {
                Text("watchOS decide cuándo sincroniza: suele hacerlo con el reloj cerca del iPhone y, a menudo, mientras carga. Puede tardar varios minutos. No existe una API para forzarla.")
                Text("En el reloj, abre la app Fotos. Usa la Digital Crown para hacer zoom en cada página.")
            }
            .font(.subheadline)
        }
        .scrollContentBackground(.hidden)
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Apple Watch")
    }
}
