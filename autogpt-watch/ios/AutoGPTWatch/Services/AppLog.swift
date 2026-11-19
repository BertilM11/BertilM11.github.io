import Foundation
import OSLog

/// Registro unificado (visible en Consola.app filtrando por "AutoGPTWatch").
enum AppLog {
    private static let logger = Logger(subsystem: Bundle.main.bundleIdentifier ?? "AutoGPTWatch", category: "app")

    static func info(_ message: String) {
        logger.info("\(message, privacy: .public)")
    }

    static func error(_ message: String) {
        logger.error("\(message, privacy: .public)")
    }
}
