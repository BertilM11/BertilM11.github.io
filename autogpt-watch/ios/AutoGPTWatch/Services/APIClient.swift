import CryptoKit
import Foundation
import AutoGPTCore

/// Llamadas en primer plano (async/await) al backend.
struct APIClient {
    let factory: APIRequestFactory
    var session: URLSession = .shared

    init(config: ServerConfiguration) {
        factory = APIRequestFactory(config: config)
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.transport("respuesta no HTTP") }
        guard (200 ..< 300).contains(http.statusCode) else {
            throw APIError.fromResponse(status: http.statusCode, body: data)
        }
        return data
    }

    private func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(type, from: data)
        } catch {
            throw APIError.decoding(String(describing: error))
        }
    }

    func health() async throws -> ServerHealth {
        let data = try await perform(factory.health())
        return try decode(ServerHealth.self, data)
    }

    func me() async throws -> ServerMe {
        let data = try await perform(factory.me())
        return try decode(ServerMe.self, data)
    }

    func job(_ id: String) async throws -> ServerJob {
        let data = try await perform(factory.job(id))
        return try decode(ServerJob.self, data)
    }

    func retry(_ id: String) async throws -> ServerJob {
        let data = try await perform(factory.retry(id))
        return try decode(ServerJob.self, data)
    }

    func selftest(preset: ResponsePreset) async throws -> ServerJob {
        let data = try await perform(factory.selftest(preset: preset))
        return try decode(ServerJob.self, data)
    }

    func jobs(statuses: [ServerJobStatus]) async throws -> [ServerJob] {
        let data = try await perform(factory.listJobs(statuses: statuses))
        return try decode(ServerJobList.self, data).jobs
    }

    func ack(_ id: String, savedNames: [String]) async throws -> ServerJob {
        let data = try await perform(factory.ack(id, savedNames: savedNames))
        return try decode(ServerJob.self, data)
    }

    func registerDevice(apnsToken: String, sandbox: Bool) async throws {
        _ = try await perform(factory.registerDevice(apnsToken: apnsToken, sandbox: sandbox))
    }

    /// Descarga un PNG, verifica su SHA-256 y lo escribe en `destination`.
    func download(_ file: ServerFile, to destination: URL, timeout: TimeInterval) async throws {
        var request = factory.download(file)
        request.timeoutInterval = max(5, timeout)
        let data = try await perform(request)
        try FileIntegrity.verify(data, sha256: file.sha256)
        try data.write(to: destination, options: .atomic)
    }
}

enum FileIntegrity {
    struct Mismatch: LocalizedError {
        var errorDescription: String? { "El archivo descargado está dañado (SHA-256 no coincide)" }
    }

    static func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func verify(_ data: Data, sha256: String) throws {
        guard sha256Hex(data) == sha256.lowercased() else { throw Mismatch() }
    }

    static func verifyFile(_ url: URL, sha256: String) -> Bool {
        guard let data = try? Data(contentsOf: url) else { return false }
        return sha256Hex(data) == sha256.lowercased()
    }
}
