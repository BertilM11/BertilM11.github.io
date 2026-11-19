import Foundation

// MARK: - Preferencias de respuesta

public enum ResponsePreset: String, CaseIterable, Codable, Sendable, Identifiable {
    case watch
    case phone

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .watch: return "Apple Watch (letra grande, 4:5)"
        case .phone: return "iPhone (pantalla completa)"
        }
    }
}

public enum ResponseLanguage: String, CaseIterable, Codable, Sendable, Identifiable {
    case spanish = "es"
    case auto

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .spanish: return "Español"
        case .auto: return "Idioma de la pregunta"
        }
    }
}

// MARK: - Selección de fotografías

/// Metadatos mínimos de un PHAsset, independientes de PhotoKit para poder probarlos.
public struct PhotoCandidate: Equatable, Sendable {
    public let id: String
    public let creationDate: Date?
    public let isScreenshot: Bool
    public let isScreenRecording: Bool
    public let isPNG: Bool
    public let isImage: Bool

    public init(id: String, creationDate: Date?, isScreenshot: Bool = false, isScreenRecording: Bool = false,
                isPNG: Bool = false, isImage: Bool = true) {
        self.id = id
        self.creationDate = creationDate
        self.isScreenshot = isScreenshot
        self.isScreenRecording = isScreenRecording
        self.isPNG = isPNG
        self.isImage = isImage
    }
}

public enum PhotoExclusionReason: String, Codable, Sendable, CaseIterable {
    case notImage
    case noDate
    case beforeSession
    case alreadyProcessed
    case screenshot
    case ownResult
    case notFromCamera
    case noText

    public var displayName: String {
        switch self {
        case .notImage: return "No es una foto"
        case .noDate: return "Sin fecha"
        case .beforeSession: return "Anterior a la sesión"
        case .alreadyProcessed: return "Ya procesada"
        case .screenshot: return "Captura de pantalla"
        case .ownResult: return "Resultado de AutoGPT Watch"
        case .notFromCamera: return "No proviene de la Cámara"
        case .noText: return "Sin texto detectable (Vision)"
        }
    }
}

public struct PhotoSelectionPolicy: Sendable {
    public var maxPerJob: Int

    public init(maxPerJob: Int = 6) {
        self.maxPerJob = maxPerJob
    }

    public func exclusionReason(for c: PhotoCandidate, sessionStart: Date,
                                processed: Set<String>, ownResults: Set<String>) -> PhotoExclusionReason? {
        if !c.isImage { return .notImage }
        if ownResults.contains(c.id) { return .ownResult }
        if processed.contains(c.id) { return .alreadyProcessed }
        guard let date = c.creationDate else { return .noDate }
        if date < sessionStart { return .beforeSession }
        if c.isScreenshot || c.isScreenRecording { return .screenshot }
        if c.isPNG { return .ownResult } // la Cámara guarda HEIC/JPEG; los PNG son resultados o capturas
        return nil
    }

    /// Devuelve los candidatos elegibles (más antiguos primero, agrupados en lotes)
    /// y los excluidos con su motivo.
    public func select(_ candidates: [PhotoCandidate], sessionStart: Date, processed: Set<String>,
                       ownResults: Set<String>) -> (batches: [[PhotoCandidate]], excluded: [(PhotoCandidate, PhotoExclusionReason)]) {
        var eligible: [PhotoCandidate] = []
        var excluded: [(PhotoCandidate, PhotoExclusionReason)] = []
        var seen = Set<String>()
        for c in candidates where seen.insert(c.id).inserted {
            if let reason = exclusionReason(for: c, sessionStart: sessionStart, processed: processed, ownResults: ownResults) {
                excluded.append((c, reason))
            } else {
                eligible.append(c)
            }
        }
        eligible.sort { ($0.creationDate ?? .distantPast) < ($1.creationDate ?? .distantPast) }
        let size = max(1, maxPerJob)
        let batches = stride(from: 0, to: eligible.count, by: size).map {
            Array(eligible[$0 ..< min($0 + size, eligible.count)])
        }
        return (batches, excluded)
    }
}

/// Heurística sobre metadatos EXIF: las fotos de la Cámara del iPhone llevan
/// TIFF.Make = "Apple" y EXIF.LensModel con "iPhone". Las imágenes guardadas desde
/// otras apps (WhatsApp, Safari...) normalmente no.
public enum CameraMetadataCheck {
    public static func looksLikeIPhoneCamera(make: String?, model: String?, lensModel: String?) -> Bool {
        let mk = (make ?? "").lowercased()
        let md = (model ?? "").lowercased()
        let lens = (lensModel ?? "").lowercased()
        guard mk.contains("apple") else { return false }
        return md.contains("iphone") || lens.contains("iphone")
    }
}

// MARK: - Filtro de relevancia (texto detectado por Vision)

public struct TextRelevancePolicy: Sendable, Equatable {
    public var minCharacters: Int

    public init(minCharacters: Int = 20) {
        self.minCharacters = minCharacters
    }

    /// Cuenta letras y dígitos reconocidos; las fotos sin texto suficiente no se envían.
    public func isRelevant(recognizedLines: [String]) -> Bool {
        let count = recognizedLines.reduce(0) { acc, line in
            acc + line.unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) }.count
        }
        return count >= minCharacters
    }
}

// MARK: - Reintentos

public enum HTTPRetryClassifier {
    public static func isTransient(statusCode: Int) -> Bool {
        statusCode == 408 || statusCode == 425 || statusCode == 429 || (500 ... 599).contains(statusCode)
    }
}

public struct RetryPolicy: Sendable, Equatable {
    public var maxAttempts: Int
    public var baseDelay: TimeInterval
    public var maxDelay: TimeInterval

    public init(maxAttempts: Int = 6, baseDelay: TimeInterval = 30, maxDelay: TimeInterval = 3600) {
        self.maxAttempts = maxAttempts
        self.baseDelay = baseDelay
        self.maxDelay = maxDelay
    }

    public func canRetry(afterAttempts attempts: Int) -> Bool { attempts < maxAttempts }

    /// Retroceso exponencial determinista (el jitter se añade fuera si se desea).
    public func delay(afterAttempts attempts: Int) -> TimeInterval {
        let exp = pow(2.0, Double(max(0, attempts - 1)))
        return min(maxDelay, baseDelay * exp)
    }
}

// MARK: - Puerta de la automatización

public enum AutomationDecision: Equatable, Sendable {
    case run
    case skip(String)
}

public struct AutomationGate: Sendable {
    public init() {}

    /// La automatización de Atajos SIEMPRE respeta el interruptor principal.
    public func evaluate(autoModeEnabled: Bool, consentGiven: Bool, photosFullAccess: Bool,
                         serverConfigured: Bool) -> AutomationDecision {
        guard autoModeEnabled else { return .skip("Modo automático desactivado.") }
        guard consentGiven else { return .skip("Falta tu consentimiento para enviar fotos al servicio de IA. Abre AutoGPT Watch.") }
        guard photosFullAccess else { return .skip("AutoGPT Watch necesita acceso completo a Fotos. Abre la app para concederlo.") }
        guard serverConfigured else { return .skip("Configura el servidor y el token en AutoGPT Watch.") }
        return .run
    }
}
