import SwiftUI

enum Theme {
    static let background = LinearGradient(
        colors: [Color(red: 0.03, green: 0.03, blue: 0.05), Color(red: 0.07, green: 0.08, blue: 0.11)],
        startPoint: .top, endPoint: .bottom
    )
    static let card = Color.white.opacity(0.06)
    static let cardBorder = Color.white.opacity(0.09)
    static let accent = Color(red: 0.22, green: 0.86, blue: 0.64)
    static let accentGradient = LinearGradient(
        colors: [Color(red: 0.42, green: 0.97, blue: 0.76), Color(red: 0.09, green: 0.62, blue: 0.48)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
    static let offGradient = LinearGradient(
        colors: [Color(white: 0.2), Color(white: 0.09)],
        startPoint: .topLeading, endPoint: .bottomTrailing
    )
    static let danger = Color(red: 1.0, green: 0.4, blue: 0.4)
    static let warning = Color(red: 1.0, green: 0.72, blue: 0.3)
    static let processing = Color(red: 0.45, green: 0.65, blue: 1.0)
    static let secondaryText = Color.white.opacity(0.6)
}

struct CardBackground: ViewModifier {
    func body(content: Content) -> some View {
        content
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).strokeBorder(Theme.cardBorder, lineWidth: 1))
    }
}

extension View {
    func card() -> some View { modifier(CardBackground()) }
}

enum AppStatus {
    case inactive, active, processing, error

    var label: String {
        switch self {
        case .inactive: return "Inactivo"
        case .active: return "Activo"
        case .processing: return "Procesando"
        case .error: return "Error"
        }
    }

    var color: Color {
        switch self {
        case .inactive: return .gray
        case .active: return Theme.accent
        case .processing: return Theme.processing
        case .error: return Theme.danger
        }
    }
}
