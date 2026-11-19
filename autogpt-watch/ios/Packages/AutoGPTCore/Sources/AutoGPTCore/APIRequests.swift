import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// Configuración de conexión con el backend propio (nunca con OpenAI directamente).
public struct ServerConfiguration: Equatable, Sendable {
    public let baseURL: URL
    public let token: String

    /// Normaliza y valida la URL: exige https y un host. Quita la barra final.
    public static func normalizedBaseURL(_ raw: String) throws -> URL {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while text.hasSuffix("/") { text.removeLast() }
        guard let url = URL(string: text),
              url.scheme?.lowercased() == "https",
              let host = url.host, !host.isEmpty,
              url.query == nil, url.fragment == nil
        else { throw APIError.invalidServerURL }
        return url
    }

    public init(baseURLString: String, token: String) throws {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw APIError.notConfigured }
        baseURL = try ServerConfiguration.normalizedBaseURL(baseURLString)
        self.token = trimmed
    }
}

/// Opciones que viajan con cada trabajo.
public struct JobOptions: Equatable, Sendable {
    public var preset: ResponsePreset
    public var language: ResponseLanguage
    public var allowIllustrations: Bool
    public var deleteUploads: Bool

    public init(preset: ResponsePreset = .watch, language: ResponseLanguage = .spanish,
                allowIllustrations: Bool = true, deleteUploads: Bool = true) {
        self.preset = preset
        self.language = language
        self.allowIllustrations = allowIllustrations
        self.deleteUploads = deleteUploads
    }
}

/// Construye las peticiones HTTP del backend. No realiza E/S: se puede probar sin red.
public struct APIRequestFactory: Sendable {
    public let config: ServerConfiguration

    public init(config: ServerConfiguration) {
        self.config = config
    }

    private func url(_ path: String, query: [URLQueryItem] = []) -> URL {
        var comps = URLComponents(url: config.baseURL, resolvingAgainstBaseURL: false)!
        let basePath = comps.path.hasSuffix("/") ? String(comps.path.dropLast()) : comps.path
        comps.path = basePath + path
        if !query.isEmpty { comps.queryItems = query }
        return comps.url!
    }

    private func request(_ method: String, _ path: String, query: [URLQueryItem] = [],
                         json: Data? = nil, timeout: TimeInterval = 30) -> URLRequest {
        var r = URLRequest(url: url(path, query: query), timeoutInterval: timeout)
        r.httpMethod = method
        r.setValue("Bearer \(config.token)", forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        if let json {
            r.httpBody = json
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return r
    }

    public func health() -> URLRequest { request("GET", "/health", timeout: 15) }
    public func me() -> URLRequest { request("GET", "/v1/me", timeout: 15) }
    public func job(_ id: String) -> URLRequest { request("GET", "/v1/jobs/\(id)") }
    public func result(_ id: String) -> URLRequest { request("GET", "/v1/jobs/\(id)/result") }
    public func retry(_ id: String) -> URLRequest { request("POST", "/v1/jobs/\(id)/retry") }

    public func listJobs(statuses: [ServerJobStatus], limit: Int = 50) -> URLRequest {
        var q = [URLQueryItem(name: "limit", value: String(limit))]
        if !statuses.isEmpty {
            q.append(URLQueryItem(name: "status", value: statuses.map(\.rawValue).joined(separator: ",")))
        }
        return request("GET", "/v1/jobs", query: q)
    }

    /// `file.url` es una ruta relativa devuelta por el servidor (/v1/jobs/{id}/files/{name}).
    public func download(_ file: ServerFile) -> URLRequest {
        var r = request("GET", file.url, timeout: 60)
        r.setValue("image/png", forHTTPHeaderField: "Accept")
        return r
    }

    public func ack(_ id: String, savedNames: [String]) -> URLRequest {
        let body = try! JSONSerialization.data(withJSONObject: ["saved": savedNames])
        return request("POST", "/v1/jobs/\(id)/ack", json: body)
    }

    public func registerDevice(apnsToken: String, sandbox: Bool) -> URLRequest {
        let body = try! JSONSerialization.data(withJSONObject: [
            "apns_token": apnsToken,
            "environment": sandbox ? "sandbox" : "production",
        ])
        return request("POST", "/v1/devices", json: body)
    }

    public func selftest(preset: ResponsePreset) -> URLRequest {
        request("POST", "/v1/selftest", query: [URLQueryItem(name: "preset", value: preset.rawValue)])
    }

    /// Petición de creación de trabajo. El cuerpo multipart se escribe aparte en un
    /// archivo (requisito de las subidas en segundo plano de URLSession).
    public func createJob(clientJobID: String, boundary: String) -> URLRequest {
        var r = request("POST", "/v1/jobs", timeout: 120)
        r.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        r.setValue(clientJobID, forHTTPHeaderField: "Idempotency-Key")
        return r
    }

    public static func createJobBody(clientJobID: String, options: JobOptions, consent: Bool,
                                     images: [Data], boundary: String) -> Data {
        var b = MultipartFormBuilder(boundary: boundary)
        b.addField("client_job_id", clientJobID)
        b.addField("consent", consent ? "true" : "false")
        b.addField("preset", options.preset.rawValue)
        b.addField("language", options.language.rawValue)
        b.addField("allow_illustrations", options.allowIllustrations ? "true" : "false")
        b.addField("delete_uploads", options.deleteUploads ? "true" : "false")
        for (i, data) in images.enumerated() {
            b.addFile("files", filename: String(format: "photo-%02d.jpg", i + 1), mimeType: "image/jpeg", data: data)
        }
        return b.finalize()
    }
}

/// Constructor de cuerpos multipart/form-data (RFC 7578).
public struct MultipartFormBuilder {
    public let boundary: String
    private var body = Data()

    public init(boundary: String = "AutoGPTWatch-\(UUID().uuidString)") {
        self.boundary = boundary
    }

    private static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "\r", with: "")
            .replacingOccurrences(of: "\n", with: "")
    }

    public mutating func addField(_ name: String, _ value: String) {
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"\(Self.escape(name))\"\r\n\r\n".utf8))
        body.append(Data(value.utf8))
        body.append(Data("\r\n".utf8))
    }

    public mutating func addFile(_ name: String, filename: String, mimeType: String, data: Data) {
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data(
            "Content-Disposition: form-data; name=\"\(Self.escape(name))\"; filename=\"\(Self.escape(filename))\"\r\n".utf8
        ))
        body.append(Data("Content-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n".utf8))
    }

    public func finalize() -> Data {
        var out = body
        out.append(Data("--\(boundary)--\r\n".utf8))
        return out
    }
}
