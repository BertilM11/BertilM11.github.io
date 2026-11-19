import SwiftUI
import UIKit

/// Genera en el iPhone una imagen PNG de PRUEBA (Fase C: guardado + Favorito) sin red ni IA.
@MainActor
enum TestImageFactory {
    struct RenderError: LocalizedError {
        var errorDescription: String? { "No se pudo generar la imagen de prueba." }
    }

    static func makePNG() throws -> URL {
        let renderer = ImageRenderer(content: TestCard(date: Date()))
        renderer.scale = 2
        guard let image = renderer.uiImage, let data = image.pngData() else { throw RenderError() }
        let url = JobFiles.temporaryFile(named: "autogpt-watch-prueba-\(UUID().uuidString.prefix(8)).png")
        try data.write(to: url, options: .atomic)
        return url
    }

    private struct TestCard: View {
        let date: Date

        var body: some View {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("AutoGPT Watch").font(.system(size: 20, weight: .bold, design: .rounded))
                    Spacer()
                    Text("PRUEBA").font(.system(size: 14, weight: .heavy)).foregroundStyle(.black)
                        .padding(.horizontal, 10).padding(.vertical, 4)
                        .background(Capsule().fill(Color(red: 0.06, green: 0.64, blue: 0.5)))
                }
                Text("Si ves esta imagen en Favoritos del iPhone y en el Apple Watch, el guardado automático funciona.")
                    .font(.system(size: 19))
                Text(date.formatted(date: .abbreviated, time: .standard))
                    .font(.system(size: 15)).foregroundStyle(.secondary)
            }
            .foregroundStyle(.white)
            .padding(22)
            .frame(width: 396, height: 484, alignment: .topLeading)
            .background(Color(red: 0.13, green: 0.13, blue: 0.13))
            .environment(\.colorScheme, .dark)
        }
    }
}
