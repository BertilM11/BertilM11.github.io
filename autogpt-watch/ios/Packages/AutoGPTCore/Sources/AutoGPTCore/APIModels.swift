import Foundation

/// Estado de un trabajo en el servidor (coincide con backend/app/db.py).
public enum ServerJobStatus: String, Codable, Sendable, CaseIterable {
    case queued, processing, completed, failed, acknowledged, expired, unknown

    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ServerJobStatus(rawValue: raw) ?? .unknown
    }
}

public struct ServerFile: Codable, Sendable, Equatable, Hashable {
    public let name: String
    public let kind: String
    public let index: Int
    public let title: String
    public let bytes: Int
    public let sha256: String
    public let url: String

    public init(name: String, kind: String, index: Int, title: String, bytes: Int, sha256: String, url: String) {
        self.name = name
        self.kind = kind
        self.index = index
        self.title = title
        self.bytes = bytes
        self.sha256 = sha256
        self.url = url
    }
}

public struct ServerJob: Codable, Sendable, Equatable {
    public let id: String
    public let clientJobID: String
    public let status: ServerJobStatus
    public let createdAt: Double
    public let updatedAt: Double
    public let attempts: Int
    public let imageCount: Int
    public let lastError: String?
    public let title: String?
    public let relevant: Bool?
    public let files: [ServerFile]
    public let completedAt: Double?
    public let ackedAt: Double?
    public let duplicate: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case clientJobID = "client_job_id"
        case status
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case attempts
        case imageCount = "image_count"
        case lastError = "last_error"
        case title
        case relevant
        case files
        case completedAt = "completed_at"
        case ackedAt = "acked_at"
        case duplicate
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        clientJobID = try c.decode(String.self, forKey: .clientJobID)
        status = try c.decode(ServerJobStatus.self, forKey: .status)
        createdAt = try c.decode(Double.self, forKey: .createdAt)
        updatedAt = try c.decodeIfPresent(Double.self, forKey: .updatedAt) ?? createdAt
        attempts = try c.decodeIfPresent(Int.self, forKey: .attempts) ?? 0
        imageCount = try c.decodeIfPresent(Int.self, forKey: .imageCount) ?? 0
        lastError = try c.decodeIfPresent(String.self, forKey: .lastError)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        relevant = try c.decodeIfPresent(Bool.self, forKey: .relevant)
        files = try c.decodeIfPresent([ServerFile].self, forKey: .files) ?? []
        completedAt = try c.decodeIfPresent(Double.self, forKey: .completedAt)
        ackedAt = try c.decodeIfPresent(Double.self, forKey: .ackedAt)
        duplicate = try c.decodeIfPresent(Bool.self, forKey: .duplicate) ?? false
    }

    /// Archivos ordenados como deben guardarse (páginas de respuesta y luego imágenes).
    public var orderedFiles: [ServerFile] {
        files.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }
}

public struct ServerJobList: Codable, Sendable {
    public let jobs: [ServerJob]
}

public struct ServerHealth: Codable, Sendable, Equatable {
    public let status: String
    public let version: String
    public let aiConfigured: Bool
    public let imageGenerationConfigured: Bool
    public let apnsEnabled: Bool

    enum CodingKeys: String, CodingKey {
        case status, version
        case aiConfigured = "ai_configured"
        case imageGenerationConfigured = "image_generation_configured"
        case apnsEnabled = "apns_enabled"
    }
}

public struct ServerMe: Codable, Sendable {
    public struct Usage: Codable, Sendable {
        public let jobs: Int
        public let images: Int
    }

    public struct Limits: Codable, Sendable {
        public let maxJobsPerDay: Int
        public let maxImagesPerDay: Int
        public let maxImagesPerJob: Int
        public let maxUploadMB: Double

        enum CodingKeys: String, CodingKey {
            case maxJobsPerDay = "max_jobs_per_day"
            case maxImagesPerDay = "max_images_per_day"
            case maxImagesPerJob = "max_images_per_job"
            case maxUploadMB = "max_upload_mb"
        }
    }

    public let owner: String
    public let usageToday: Usage
    public let limits: Limits
    public let aiConfigured: Bool

    enum CodingKeys: String, CodingKey {
        case owner
        case usageToday = "usage_today"
        case limits
        case aiConfigured = "ai_configured"
    }
}

public struct ServerErrorBody: Codable, Sendable {
    public let detail: String
}

public enum APIError: Error, LocalizedError, Equatable, Sendable {
    case notConfigured
    case invalidServerURL
    case http(status: Int, detail: String)
    case decoding(String)
    case transport(String)

    public var errorDescription: String? {
        switch self {
        case .notConfigured: return "Configura la URL del servidor y el token en Ajustes."
        case .invalidServerURL: return "La URL del servidor debe empezar por https://"
        case let .http(status, detail): return "Servidor (\(status)): \(detail)"
        case let .decoding(msg): return "Respuesta inesperada del servidor: \(msg)"
        case let .transport(msg): return "Error de red: \(msg)"
        }
    }

    /// ¿Merece la pena reintentar automáticamente?
    public var isTransient: Bool {
        switch self {
        case let .http(status, _): return HTTPRetryClassifier.isTransient(statusCode: status)
        case .transport: return true
        default: return false
        }
    }

    public static func fromResponse(status: Int, body: Data) -> APIError {
        let detail = (try? JSONDecoder().decode(ServerErrorBody.self, from: body).detail)
            ?? String(data: body.prefix(300), encoding: .utf8) ?? ""
        return .http(status: status, detail: detail)
    }
}
