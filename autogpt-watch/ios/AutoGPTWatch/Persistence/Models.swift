import Foundation
import SwiftData
import AutoGPTCore

/// Trabajo local: un lote de fotos enviado al servidor y sus resultados.
@Model
final class LocalJob {
    @Attribute(.unique) var id: UUID
    var createdAt: Date
    var updatedAt: Date
    var phaseRaw: String
    var serverJobID: String?
    var assetIDs: [String]
    var photoCount: Int
    var attempts: Int
    var lastError: String?
    var nextAttemptAt: Date?
    var title: String?
    var expectedFiles: [String]
    var expectedHashes: [String]
    var uploadBoundary: String?
    var savedFiles: [String]
    var savedAssetIDs: [String]
    var completedAt: Date?
    var isSelfTest: Bool

    init(id: UUID = UUID(), assetIDs: [String], phase: JobPhase, isSelfTest: Bool = false) {
        self.id = id
        createdAt = .now
        updatedAt = .now
        phaseRaw = phase.rawValue
        serverJobID = nil
        self.assetIDs = assetIDs
        photoCount = assetIDs.count
        attempts = 0
        lastError = nil
        nextAttemptAt = nil
        title = nil
        expectedFiles = []
        expectedHashes = []
        uploadBoundary = nil
        savedFiles = []
        savedAssetIDs = []
        completedAt = nil
        self.isSelfTest = isSelfTest
    }

    var phase: JobPhase {
        JobPhase(rawValue: phaseRaw) ?? .failed
    }

    /// Cambia de fase respetando las transiciones permitidas. Devuelve false si no es válida.
    @discardableResult
    func move(to next: JobPhase, error: String? = nil) -> Bool {
        guard phase.canTransition(to: next) else { return false }
        phaseRaw = next.rawValue
        updatedAt = .now
        if let error { lastError = error } else if next != .retryWait && next != .failed { lastError = nil }
        if next == .saved || next == .noAnswer { completedAt = .now }
        return true
    }

    /// Marca en `savedFiles` de un trabajo sin respuesta ya confirmado al servidor.
    static let ackedMarker = "__acked__"

    var displayTitle: String {
        if let title, !title.isEmpty { return title }
        return isSelfTest ? "Prueba de funcionamiento" : (photoCount == 1 ? "1 foto" : "\(photoCount) fotos")
    }
}

/// Fotografía ya evaluada (enviada u omitida). Evita reprocesar duplicados.
@Model
final class ProcessedAsset {
    @Attribute(.unique) var localIdentifier: String
    var processedAt: Date
    var outcomeRaw: String
    var jobID: UUID?

    init(localIdentifier: String, outcome: String, jobID: UUID?) {
        self.localIdentifier = localIdentifier
        processedAt = .now
        outcomeRaw = outcome
        self.jobID = jobID
    }

    static let sentOutcome = "sent"
}

/// Imagen generada y guardada en Fotos como Favorita.
@Model
final class SavedResult {
    @Attribute(.unique) var assetLocalIdentifier: String
    var jobID: UUID?
    var fileName: String
    var title: String
    var savedAt: Date

    init(assetLocalIdentifier: String, jobID: UUID?, fileName: String, title: String) {
        self.assetLocalIdentifier = assetLocalIdentifier
        self.jobID = jobID
        self.fileName = fileName
        self.title = title
        savedAt = .now
    }
}
