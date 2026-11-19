import Foundation

/// URLSession en segundo plano: iOS continúa las subidas/descargas aunque la app se
/// suspenda o se cierre, y la relanza en segundo plano al terminar
/// (application(_:handleEventsForBackgroundURLSession:completionHandler:)).
final class BackgroundTransferManager: NSObject, URLSessionDataDelegate, URLSessionDownloadDelegate, @unchecked Sendable {
    static let shared = BackgroundTransferManager()

    static var identifier: String {
        (Bundle.main.bundleIdentifier ?? "AutoGPTWatch") + ".transfers"
    }

    private let lock = NSLock()
    private var responseBodies: [Int: Data] = [:]
    private var completionHandler: (() -> Void)?

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: Self.identifier)
        config.isDiscretionary = false
        config.sessionSendsLaunchEvents = true
        config.allowsCellularAccess = true
        config.timeoutIntervalForResource = 24 * 60 * 60
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    /// Debe llamarse al arrancar para reconectar con las transferencias pendientes.
    func activate() {
        _ = session
    }

    func setBackgroundCompletionHandler(_ handler: @escaping () -> Void) {
        lock.lock()
        completionHandler = handler
        lock.unlock()
        activate()
    }

    // MARK: Tareas

    func startUpload(request: URLRequest, bodyFile: URL, localJobID: UUID) {
        let task = session.uploadTask(with: request, fromFile: bodyFile)
        task.taskDescription = TaskTag.upload(localJobID).encoded
        task.resume()
        AppLog.info("Subida iniciada \(localJobID)")
    }

    func startDownload(request: URLRequest, localJobID: UUID, fileName: String) {
        let task = session.downloadTask(with: request)
        task.taskDescription = TaskTag.download(localJobID, fileName).encoded
        task.resume()
    }

    /// Identificadores de trabajos con transferencias activas (para no duplicarlas).
    func activeTags() async -> [TaskTag] {
        let tasks = await session.allTasks
        return tasks.compactMap { $0.taskDescription.flatMap(TaskTag.init(encoded:)) }
    }

    // MARK: URLSessionDataDelegate (cuerpo de la respuesta a la subida)

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock()
        responseBodies[dataTask.taskIdentifier, default: Data()].append(data)
        lock.unlock()
    }

    // MARK: URLSessionDownloadDelegate

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        // El archivo temporal se borra al volver de este método: hay que moverlo ya.
        guard case let .download(jobID, name)? = downloadTask.taskDescription.flatMap(TaskTag.init(encoded:)) else { return }
        let status = (downloadTask.response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200 ..< 300).contains(status) else { return }
        let destination = JobFiles.resultFile(for: jobID, name: name + ".download")
        JobFiles.remove(destination)
        do {
            try FileManager.default.moveItem(at: location, to: destination)
        } catch {
            AppLog.error("No se pudo mover la descarga: \(error.localizedDescription)")
        }
    }

    // MARK: URLSessionTaskDelegate

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let tag = task.taskDescription.flatMap(TaskTag.init(encoded:)) else { return }
        let status = (task.response as? HTTPURLResponse)?.statusCode
        lock.lock()
        let body = responseBodies.removeValue(forKey: task.taskIdentifier) ?? Data()
        lock.unlock()
        let errorText = error?.localizedDescription
        Task { @MainActor in
            let coordinator = AppServices.shared.coordinator
            switch tag {
            case let .upload(jobID):
                await coordinator.uploadFinished(localJobID: jobID, statusCode: status, body: body, transportError: errorText)
            case let .download(jobID, name):
                await coordinator.backgroundDownloadFinished(localJobID: jobID, fileName: name,
                                                             statusCode: status, transportError: errorText)
            }
        }
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        lock.lock()
        let handler = completionHandler
        completionHandler = nil
        lock.unlock()
        Task { @MainActor in
            // Terminar de guardar lo que haya quedado listo antes de devolver el control a iOS.
            await AppServices.shared.coordinator.finishPendingSaves()
            handler?()
        }
    }
}

/// Etiqueta persistida en `taskDescription` para reconocer la tarea tras un relanzamiento.
enum TaskTag: Equatable {
    case upload(UUID)
    case download(UUID, String)

    var encoded: String {
        switch self {
        case let .upload(id): return "upload|\(id.uuidString)"
        case let .download(id, name): return "download|\(id.uuidString)|\(name)"
        }
    }

    init?(encoded: String) {
        let parts = encoded.split(separator: "|", maxSplits: 2).map(String.init)
        guard parts.count >= 2, let id = UUID(uuidString: parts[1]) else { return nil }
        switch parts[0] {
        case "upload": self = .upload(id)
        case "download" where parts.count == 3: self = .download(id, parts[2])
        default: return nil
        }
    }

    var jobID: UUID {
        switch self {
        case let .upload(id), let .download(id, _): return id
        }
    }
}
