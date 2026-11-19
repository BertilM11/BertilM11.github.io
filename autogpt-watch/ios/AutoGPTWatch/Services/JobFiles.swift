import Foundation

/// Ubicaciones en disco (Application Support, excluidas de la copia de seguridad).
enum JobFiles {
    private static var root: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("AutoGPTWatch", isDirectory: true)
        if !FileManager.default.fileExists(atPath: dir.path) {
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            var mutable = dir
            try? mutable.setResourceValues(values)
        }
        return dir
    }

    /// Cuerpo multipart pendiente de subir (se conserva hasta que el servidor lo acepta).
    static func outboxFile(for jobID: UUID) -> URL {
        let dir = root.appendingPathComponent("Outbox", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("\(jobID.uuidString).multipart")
    }

    /// Carpeta con los PNG descargados de un trabajo.
    static func resultsDirectory(for jobID: UUID) -> URL {
        let dir = root.appendingPathComponent("Results", isDirectory: true)
            .appendingPathComponent(jobID.uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func resultFile(for jobID: UUID, name: String) -> URL {
        resultsDirectory(for: jobID).appendingPathComponent(name)
    }

    static func temporaryFile(named name: String) -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(name)
    }

    static func remove(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }
}
