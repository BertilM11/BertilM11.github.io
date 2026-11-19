import SwiftUI

/// Consentimiento explícito antes del primer envío de fotos al servicio de IA.
struct ConsentView: View {
    let onDecision: (Bool) -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Image(systemName: "hand.raised.square.on.square")
                        .font(.system(size: 44))
                        .foregroundStyle(Theme.accent)
                    Text("Antes de empezar")
                        .font(.system(size: 28, weight: .bold, design: .rounded))
                    point("camera", "Mientras el modo automático esté activo, AutoGPT Watch revisa las fotos NUEVAS tomadas con la Cámara durante la sesión.")
                    point("text.viewfinder", "Vision analiza cada foto en el iPhone y descarta las que no contienen texto. Las capturas de pantalla y las imágenes de otras apps no se envían.")
                    point("arrow.up.doc", "Las fotos elegibles se envían, reducidas y sin ubicación ni metadatos, a TU servidor, que las reenvía al servicio de IA de OpenAI para generar las respuestas.")
                    point("trash", "Tu servidor puede borrar las fotos en cuanto termina el análisis (opción activada por defecto).")
                    point("heart", "Las respuestas se guardan en Fotos como Favoritas. Tus fotos originales nunca se modifican ni se borran.")
                    point("exclamationmark.triangle", "No uses la app con documentos que no tengas derecho a compartir ni para infringir normas de exámenes o evaluaciones.")
                }
                .padding(24)
            }
            .background(Theme.background.ignoresSafeArea())
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 10) {
                    Button {
                        onDecision(true)
                    } label: {
                        Text("Acepto el envío de fotos")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    Button("Ahora no") { onDecision(false) }
                        .foregroundStyle(Theme.secondaryText)
                }
                .padding(20)
                .background(.ultraThinMaterial)
            }
        }
    }

    private func point(_ icon: String, _ text: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Theme.accent)
                .frame(width: 26)
            Text(text).font(.body)
        }
    }
}
