import Combine
import Foundation
import Photos
import UIKit
import AutoGPTCore

struct ProcessSummary {
    var message: String
    var sentPhotos = 0
    var skippedPhotos = 0
    var failedPhotos = 0
    var savedJobs = 0
}

enum CoordinatorError: LocalizedError {
    case timeout(String)
    case failed(String)

    var errorDescription: String? {
        switch self {
        case let .timeout(m), let .failed(m): return m
        }
    }
}

/// Orquesta todo el flujo. Cualquier punto de entrada (Atajo al cerrar Cámara, push,
/// refresco en segundo plano, apertura de la app) llama aquí y el trabajo se retoma
/// desde su fase persistida.
@MainActor
final class ProcessingCoordinator: ObservableObject {
    @Published private(set) var isBusy = false
    @Published private(set) var lastMessage: String?
    @Published private(set) var revision = 0

    private let settings: SettingsStore
    private let store: JobStore
    private let photos: PhotoLibraryService
    private let notifications: NotificationManager
    private let transfers = BackgroundTransferManager.shared
    private let retryPolicy = RetryPolicy()
    private let selectionPolicy = PhotoSelectionPolicy(maxPerJob: 6)

    private var isScanning = false
    private var isSyncing = false
    private var savingJobs = Set<UUID>()
    private var busyCount = 0 {
        didSet { isBusy = busyCount > 0 }
    }

    init(settings: SettingsStore, store: JobStore, photos: PhotoLibraryService, notifications: NotificationManager) {
        self.settings = settings
        self.store = store
        self.photos = photos
        self.notifications = notifications
    }

    var hasPendingWork: Bool {
        !store.jobs(in: Set(JobPhase.allCases.filter(\.isPending))).isEmpty
    }

    // MARK: - Modo automático

    func setAutoMode(_ enabled: Bool) {
        if enabled {
            settings.sessionStart = Date()
            settings.autoModeEnabled = true
            lastMessage = "Sesión iniciada. Toma fotos con la Cámara."
        } else {
            settings.autoModeEnabled = false
            lastMessage = "Modo automático desactivado."
        }
        revision += 1
    }

    /// Al volver a primer plano: recupera fotos y resultados pendientes.
    func onForeground() async {
        if settings.autoModeEnabled {
            let summary = await processPendingPhotos(deadline: Date().addingTimeInterval(60))
            lastMessage = summary.message
        } else {
            await syncResults(deadline: Date().addingTimeInterval(60))
        }
    }

    // MARK: - 1) Detección y envío de fotos

    func processPendingPhotos(deadline: Date = Date().addingTimeInterval(25)) async -> ProcessSummary {
        let decision = AutomationGate().evaluate(
            autoModeEnabled: settings.autoModeEnabled,
            consentGiven: settings.consentGiven,
            photosFullAccess: PhotoLibraryService.hasFullAccess,
            serverConfigured: settings.serverConfiguration != nil
        )
        if case let .skip(reason) = decision {
            return ProcessSummary(message: reason)
        }
        guard !isScanning else { return ProcessSummary(message: "Ya hay un procesamiento en curso.") }
        guard let sessionStart = settings.sessionStart else {
            return ProcessSummary(message: "No hay una sesión activa. Activa el modo automático.")
        }
        isScanning = true
        busyCount += 1
        defer {
            isScanning = false
            busyCount -= 1
            revision += 1
        }

        var summary = ProcessSummary(message: "")
        let found = photos.fetchCandidates(since: sessionStart)
        let processed = store.processedIDs()
        let selection = selectionPolicy.select(found.map { $0.candidate }, sessionStart: sessionStart,
                                               processed: processed, ownResults: store.ownResultIDs())
        // Registrar exclusiones definitivas para no volver a evaluarlas.
        let permanent: Set<PhotoExclusionReason> = [.screenshot, .ownResult, .notImage]
        for (candidate, reason) in selection.excluded where permanent.contains(reason) && !processed.contains(candidate.id) {
            store.markProcessed([candidate.id], outcome: reason.rawValue, jobID: nil)
        }

        let assets = Dictionary(found.map { ($0.candidate.id, $0.asset) }, uniquingKeysWith: { first, _ in first })
        let textPolicy = TextRelevancePolicy(minCharacters: settings.visionMinCharacters)
        for batch in selection.batches {
            var images: [Data] = []
            var ids: [String] = []
            for candidate in batch {
                guard let asset = assets[candidate.id] else { continue }
                do {
                    let data = try await photos.imageData(for: asset)
                    let prepared = try ImagePipeline.prepare(data)
                    if settings.requireCameraMetadata && !prepared.looksLikeCameraPhoto {
                        store.markProcessed([candidate.id], outcome: PhotoExclusionReason.notFromCamera.rawValue, jobID: nil)
                        summary.skippedPhotos += 1
                        continue
                    }
                    if settings.visionFilterEnabled {
                        let lines = try await ImagePipeline.recognizeText(in: prepared.cgImage)
                        if !textPolicy.isRelevant(recognizedLines: lines) {
                            store.markProcessed([candidate.id], outcome: PhotoExclusionReason.noText.rawValue, jobID: nil)
                            summary.skippedPhotos += 1
                            continue
                        }
                    }
                    images.append(prepared.jpeg)
                    ids.append(candidate.id)
                } catch {
                    // No se marca como procesada: se reintentará en la próxima ejecución.
                    AppLog.error("Foto \(candidate.id): \(error.localizedDescription)")
                    summary.failedPhotos += 1
                }
            }
            if !images.isEmpty, createJob(assetIDs: ids, images: images) {
                summary.sentPhotos += ids.count
            }
        }
        store.save()

        if deadline.timeIntervalSinceNow > 5 {
            summary.savedJobs = await syncResults(deadline: deadline)
        }
        summary.message = Self.describe(summary)
        lastMessage = summary.message
        return summary
    }

    private static func describe(_ s: ProcessSummary) -> String {
        var parts: [String] = []
        if s.sentPhotos > 0 { parts.append("Enviadas \(s.sentPhotos) foto(s) para analizar.") }
        if s.skippedPhotos > 0 { parts.append("Omitidas \(s.skippedPhotos) (sin texto o no son de la Cámara).") }
        if s.failedPhotos > 0 { parts.append("\(s.failedPhotos) foto(s) no se pudieron leer; se reintentará.") }
        if s.savedJobs > 0 { parts.append("Guardadas en Favoritos las respuestas de \(s.savedJobs) trabajo(s).") }
        return parts.isEmpty ? "No hay fotos nuevas en esta sesión." : parts.joined(separator: " ")
    }

    /// Crea el trabajo local, escribe el cuerpo multipart en disco y lanza la subida.
    private func createJob(assetIDs: [String], images: [Data]) -> Bool {
        let job = LocalJob(assetIDs: assetIDs, phase: .pendingUpload)
        let boundary = "AutoGPTWatch-\(UUID().uuidString)"
        let body = APIRequestFactory.createJobBody(clientJobID: job.id.uuidString, options: settings.jobOptions,
                                                   consent: settings.consentGiven, images: images, boundary: boundary)
        do {
            try body.write(to: JobFiles.outboxFile(for: job.id), options: .atomic)
        } catch {
            AppLog.error("No se pudo preparar el envío: \(error.localizedDescription)")
            return false
        }
        job.uploadBoundary = boundary
        store.insert(job)
        // Se marcan como procesadas ANTES de subir: si la app muere, el trabajo se
        // retoma desde el Outbox y las fotos nunca se envían dos veces.
        store.markProcessed(assetIDs, outcome: ProcessedAsset.sentOutcome, jobID: job.id)
        store.save()
        startUpload(job)
        return true
    }

    private func startUpload(_ job: LocalJob) {
        guard let config = settings.serverConfiguration else {
            job.move(to: .retryWait, error: APIError.notConfigured.localizedDescription)
            job.nextAttemptAt = Date().addingTimeInterval(retryPolicy.baseDelay)
            return
        }
        let file = JobFiles.outboxFile(for: job.id)
        guard let boundary = job.uploadBoundary, FileManager.default.fileExists(atPath: file.path) else {
            job.move(to: .failed, error: "El paquete de fotos ya no existe en el iPhone.")
            store.save()
            return
        }
        guard retryPolicy.canRetry(afterAttempts: job.attempts) else {
            job.move(to: .failed, error: job.lastError ?? "Demasiados intentos de envío.")
            store.save()
            return
        }
        let request = APIRequestFactory(config: config).createJob(clientJobID: job.id.uuidString, boundary: boundary)
        job.attempts += 1
        job.move(to: .uploading)
        store.save()
        transfers.startUpload(request: request, bodyFile: file, localJobID: job.id)
    }

    /// Respuesta de la subida (puede llegar con la app relanzada en segundo plano).
    func uploadFinished(localJobID: UUID, statusCode: Int?, body: Data, transportError: String?) async {
        guard let job = store.job(id: localJobID) else { return }
        if let status = statusCode, (200 ..< 300).contains(status),
           let server = try? JSONDecoder().decode(ServerJob.self, from: body) {
            job.serverJobID = server.id
            apply(server, to: job)
            JobFiles.remove(JobFiles.outboxFile(for: job.id))
            store.save()
            revision += 1
            if job.phase == .ready {
                await syncResults(deadline: Date().addingTimeInterval(20))
            }
            return
        }
        let error: APIError = statusCode.map { APIError.fromResponse(status: $0, body: body) }
            ?? .transport(transportError ?? "sin respuesta del servidor")
        fail(job, error: error)
        store.save()
        revision += 1
    }

    private func fail(_ job: LocalJob, error: APIError) {
        let message = error.localizedDescription
        if error.isTransient && retryPolicy.canRetry(afterAttempts: job.attempts) {
            job.nextAttemptAt = Date().addingTimeInterval(retryPolicy.delay(afterAttempts: max(1, job.attempts)))
            job.move(to: .retryWait, error: message)
            BackgroundRefresh.schedule(after: retryPolicy.delay(afterAttempts: max(1, job.attempts)))
        } else {
            job.move(to: .failed, error: message)
        }
    }

    // MARK: - 2) Sincronización de resultados

    /// Retoma subidas, consulta el servidor, descarga y guarda en Fotos lo que esté listo.
    /// Devuelve cuántos trabajos se guardaron.
    @discardableResult
    func syncResults(deadline: Date) async -> Int {
        guard let config = settings.serverConfiguration else { return 0 }
        guard !isSyncing else { return 0 }
        isSyncing = true
        busyCount += 1
        defer {
            isSyncing = false
            busyCount -= 1
            revision += 1
        }
        let api = APIClient(config: config)
        await registerPushIfNeeded(api: api)

        // a) Reintentos vencidos.
        for job in store.jobs(in: [.retryWait]) where (job.nextAttemptAt ?? .distantPast) <= Date() {
            job.move(to: job.serverJobID == nil ? .pendingUpload : .processing)
        }
        // b) Subidas pendientes o atascadas.
        let active = Set(await transfers.activeTags().map(\.jobID))
        for job in store.jobs(in: [.pendingUpload]) where !active.contains(job.id) {
            startUpload(job)
        }
        for job in store.jobs(in: [.uploading]) where !active.contains(job.id) && job.updatedAt < Date().addingTimeInterval(-120) {
            job.move(to: .pendingUpload)
            startUpload(job)
        }
        // c) Recuperación: trabajos del servidor cuya respuesta de subida se perdió
        //    o que no existen localmente (p. ej. tras reinstalar la app).
        if let remote = try? await api.jobs(statuses: [.queued, .processing, .completed, .failed]) {
            for server in remote where store.job(serverID: server.id) == nil {
                if let localID = UUID(uuidString: server.clientJobID), let local = store.job(id: localID) {
                    local.serverJobID = server.id
                    JobFiles.remove(JobFiles.outboxFile(for: local.id))
                    apply(server, to: local)
                } else if server.status == .completed {
                    let adopted = LocalJob(id: UUID(uuidString: server.clientJobID) ?? UUID(), assetIDs: [],
                                           phase: .processing, isSelfTest: server.clientJobID.hasPrefix("selftest-"))
                    adopted.photoCount = server.imageCount
                    adopted.serverJobID = server.id
                    store.insert(adopted)
                    apply(server, to: adopted)
                }
            }
        }
        // d) Estado de los trabajos en curso.
        for job in store.jobs(in: [.processing, .ready, .downloading]) {
            guard let serverID = job.serverJobID, deadline.timeIntervalSinceNow > 3 else { continue }
            do {
                let server = try await api.job(serverID)
                apply(server, to: job)
            } catch let error as APIError {
                if case let .http(status, _) = error, status == 404 {
                    job.move(to: .failed, error: "El servidor ya no tiene este trabajo.")
                }
            } catch {}
        }
        store.save()
        // e) Descargar y guardar.
        var saved = 0
        for job in store.jobs(in: [.ready, .downloading, .saving]) {
            guard deadline.timeIntervalSinceNow > 2 else { break }
            if await downloadAndSave(job, api: api, deadline: deadline) { saved += 1 }
        }
        // f) Trabajos sin respuesta (fotos sin ejercicios): confirmar para que el servidor limpie.
        for job in store.jobs(in: [.noAnswer]) where job.serverJobID != nil && !job.savedFiles.contains(LocalJob.ackedMarker) {
            guard deadline.timeIntervalSinceNow > 2, let serverID = job.serverJobID else { break }
            if (try? await api.ack(serverID, savedNames: [])) != nil {
                job.savedFiles = [LocalJob.ackedMarker]
            }
        }
        store.save()
        if hasPendingWork { BackgroundRefresh.schedule() }
        return saved
    }

    private func apply(_ server: ServerJob, to job: LocalJob) {
        if let title = server.title, !title.isEmpty { job.title = title }
        if !server.files.isEmpty {
            job.expectedFiles = server.orderedFiles.map(\.name)
            job.expectedHashes = server.orderedFiles.map(\.sha256)
        }
        let target = JobPhase.from(server: server)
        switch target {
        case .failed:
            job.move(to: .failed, error: server.lastError ?? (server.status == .expired
                ? "Los resultados caducaron en el servidor." : "El servidor no pudo procesar las fotos."))
        case .saved:
            job.move(to: .saved)
        case .ready:
            if job.phase == .processing || job.phase == .uploading || job.phase == .pendingUpload || job.phase == .retryWait {
                job.move(to: .ready)
            }
        default:
            job.move(to: target)
        }
    }

    // MARK: - 3) Descarga y guardado en Fotos

    private func downloadAndSave(_ job: LocalJob, api: APIClient, deadline: Date) async -> Bool {
        guard !savingJobs.contains(job.id) else { return false }
        savingJobs.insert(job.id)
        defer { savingJobs.remove(job.id) }

        if !job.expectedFiles.isEmpty && Set(job.savedFiles) == Set(job.expectedFiles) {
            return await acknowledge(job, api: api)
        }
        guard let serverID = job.serverJobID else { return false }
        let server: ServerJob
        do {
            server = try await api.job(serverID)
        } catch {
            return false
        }
        apply(server, to: job)
        let files = server.orderedFiles
        guard server.status == .completed, !files.isEmpty else { return false }
        job.move(to: .downloading)

        var missing: [ServerFile] = []
        for file in files {
            let destination = JobFiles.resultFile(for: job.id, name: file.name)
            if FileIntegrity.verifyFile(destination, sha256: file.sha256) { continue }
            if adoptBackgroundDownload(jobID: job.id, name: file.name, sha256: file.sha256) { continue }
            let remaining = deadline.timeIntervalSinceNow
            if remaining > 4 {
                do {
                    try await api.download(file, to: destination, timeout: min(30, remaining - 2))
                    continue
                } catch {
                    AppLog.error("Descarga \(file.name): \(error.localizedDescription)")
                }
            }
            missing.append(file)
        }
        if !missing.isEmpty {
            // Sin tiempo o sin red: iOS continúa la descarga en segundo plano.
            let active = await transfers.activeTags()
            for file in missing where !active.contains(.download(job.id, file.name)) {
                transfers.startDownload(request: api.factory.download(file), localJobID: job.id, fileName: file.name)
            }
            store.save()
            return false
        }
        return await saveToPhotos(job, api: api)
    }

    /// Mueve a su sitio un archivo descargado por la sesión en segundo plano si es íntegro.
    private func adoptBackgroundDownload(jobID: UUID, name: String, sha256: String) -> Bool {
        let temp = JobFiles.resultFile(for: jobID, name: name + ".download")
        guard FileIntegrity.verifyFile(temp, sha256: sha256) else { return false }
        let destination = JobFiles.resultFile(for: jobID, name: name)
        JobFiles.remove(destination)
        do {
            try FileManager.default.moveItem(at: temp, to: destination)
            return true
        } catch {
            return false
        }
    }

    /// ¿Están todos los archivos esperados en disco y verificados?
    private func allFilesPresent(_ job: LocalJob) -> Bool {
        guard !job.expectedFiles.isEmpty, job.expectedFiles.count == job.expectedHashes.count else { return false }
        for (name, hash) in zip(job.expectedFiles, job.expectedHashes) {
            let destination = JobFiles.resultFile(for: job.id, name: name)
            if FileIntegrity.verifyFile(destination, sha256: hash) { continue }
            if adoptBackgroundDownload(jobID: job.id, name: name, sha256: hash) { continue }
            return false
        }
        return true
    }

    private func saveToPhotos(_ job: LocalJob, api: APIClient?) async -> Bool {
        guard PhotoLibraryService.hasFullAccess else {
            job.move(to: .ready, error: PhotoLibraryError.notAuthorized.localizedDescription)
            store.save()
            notifyNeedsAttention(job)
            return false
        }
        let names = job.expectedFiles
        let urls = names.map { JobFiles.resultFile(for: job.id, name: $0) }
        job.move(to: .saving)
        store.save()

        let assertion = BackgroundTaskAssertion(name: "save-results")
        defer { assertion.end() }
        do {
            let ids = try await photos.saveFavorites(
                fileURLs: urls,
                creationDates: ResultOrdering.creationDates(start: Date(), count: urls.count),
                albumName: settings.createAlbum ? SettingsStore.albumName : nil
            )
            for (id, name) in zip(ids, names) {
                store.addSavedResult(SavedResult(assetLocalIdentifier: id, jobID: job.id, fileName: name, title: job.displayTitle))
            }
            job.savedAssetIDs = ids
            job.savedFiles = names
            store.save()
        } catch {
            job.attempts += 1
            job.move(to: .ready, error: error.localizedDescription)
            store.save()
            notifyNeedsAttention(job)
            return false
        }

        _ = await acknowledge(job, api: api)
        if settings.notifyOnSave && UIApplication.shared.applicationState != .active && !job.isSelfTest {
            notifications.post(title: job.displayTitle,
                               body: "\(names.count) imagen(es) guardadas en Favoritos. Se sincronizarán con el Apple Watch.")
        }
        notifications.clearDelivered()
        return true
    }

    private func notifyNeedsAttention(_ job: LocalJob) {
        guard UIApplication.shared.applicationState != .active else { return }
        notifications.post(title: "AutoGPT Watch",
                           body: "Respuestas listas de «\(job.displayTitle)». Abre la app para terminar de guardarlas.",
                           identifier: "needs-save-\(job.id.uuidString)")
    }

    /// Confirma al servidor que todo está en Fotos. Si falla, se reintenta en la próxima sincronización.
    private func acknowledge(_ job: LocalJob, api: APIClient?) async -> Bool {
        guard let serverID = job.serverJobID, let api else { return false }
        do {
            _ = try await api.ack(serverID, savedNames: job.savedFiles)
        } catch let error as APIError {
            if case let .http(status, _) = error, [404, 409, 410].contains(status) {
                // El servidor ya lo dio por cerrado/caducado: lo importante (Fotos) está hecho.
            } else {
                job.lastError = "Guardado en Fotos; falta confirmarlo al servidor."
                store.save()
                return false
            }
        } catch {
            return false
        }
        job.move(to: .saved)
        try? FileManager.default.removeItem(at: JobFiles.resultsDirectory(for: job.id))
        store.save()
        revision += 1
        return true
    }

    // MARK: - Eventos del sistema

    /// Archivos descargados por la sesión en segundo plano.
    func backgroundDownloadFinished(localJobID: UUID, fileName: String, statusCode: Int?, transportError: String?) async {
        if let transportError {
            AppLog.error("Descarga en segundo plano \(fileName): \(transportError)")
            return
        }
        if let statusCode, !(200 ..< 300).contains(statusCode) {
            AppLog.error("Descarga en segundo plano \(fileName): HTTP \(statusCode)")
            return
        }
        await finishPendingSaves()
    }

    /// Guarda en Fotos los trabajos cuyos archivos ya están completos en disco.
    func finishPendingSaves() async {
        let api = settings.serverConfiguration.map { APIClient(config: $0) }
        for job in store.jobs(in: [.ready, .downloading, .saving]) where !savingJobs.contains(job.id) {
            savingJobs.insert(job.id)
            if !job.expectedFiles.isEmpty && Set(job.savedFiles) == Set(job.expectedFiles) {
                _ = await acknowledge(job, api: api)
            } else if allFilesPresent(job) {
                _ = await saveToPhotos(job, api: api)
            }
            savingJobs.remove(job.id)
        }
    }

    func handleRemoteNotification() async -> UIBackgroundFetchResult {
        let saved = await syncResults(deadline: Date().addingTimeInterval(25))
        return saved > 0 ? .newData : .noData
    }

    // MARK: - Push

    func registerPushToken(_ hexToken: String) async {
        settings.apnsToken = hexToken
        if let config = settings.serverConfiguration {
            await registerPushIfNeeded(api: APIClient(config: config))
        }
    }

    private func registerPushIfNeeded(api: APIClient) async {
        guard let token = settings.apnsToken else { return }
        let key = "\(api.factory.config.baseURL.absoluteString)|\(token)"
        guard settings.apnsRegisteredFor != key else { return }
        #if DEBUG
        let sandbox = true
        #else
        let sandbox = false
        #endif
        do {
            try await api.registerDevice(apnsToken: token, sandbox: sandbox)
            settings.apnsRegisteredFor = key
        } catch {
            AppLog.error("Registro push: \(error.localizedDescription)")
        }
    }

    // MARK: - Acciones manuales

    func syncNow() async {
        await syncResults(deadline: Date().addingTimeInterval(90))
    }

    func retry(_ job: LocalJob) async {
        job.lastError = nil
        job.attempts = 0
        if let serverID = job.serverJobID, let config = settings.serverConfiguration {
            let api = APIClient(config: config)
            if let server = try? await api.job(serverID) {
                if server.status == .failed, let retried = try? await api.retry(serverID) {
                    job.move(to: .processing)
                    apply(retried, to: job)
                } else if server.status != .failed {
                    job.move(to: .processing)
                    apply(server, to: job)
                } else {
                    job.lastError = server.lastError ?? "El servidor no aceptó el reintento."
                }
            } else {
                job.lastError = "No se pudo contactar con el servidor."
            }
        } else {
            job.move(to: .pendingUpload)
        }
        store.save()
        await syncNow()
    }

    func discard(_ job: LocalJob) {
        JobFiles.remove(JobFiles.outboxFile(for: job.id))
        try? FileManager.default.removeItem(at: JobFiles.resultsDirectory(for: job.id))
        store.delete(job)
        store.save()
        revision += 1
    }

    // MARK: - Pruebas de funcionamiento

    /// Fase C: genera una imagen de PRUEBA en el iPhone y la guarda como Favorita.
    func saveLocalTestImage() async throws -> String {
        let url = try TestImageFactory.makePNG()
        defer { JobFiles.remove(url) }
        let ids = try await photos.saveFavorites(fileURLs: [url], creationDates: [Date()],
                                                 albumName: settings.createAlbum ? SettingsStore.albumName : nil)
        for id in ids {
            store.addSavedResult(SavedResult(assetLocalIdentifier: id, jobID: nil, fileName: url.lastPathComponent,
                                             title: "Prueba local"))
        }
        store.save()
        guard let first = ids.first, photos.verifyFavorites(ids) else {
            throw CoordinatorError.failed("La imagen se guardó pero no aparece como Favorita.")
        }
        return first
    }

    /// Prueba de extremo a extremo SIN IA: el servidor renderiza una página de PRUEBA,
    /// el iPhone la descarga, la guarda como Favorita y confirma.
    func runServerSelfTest() async throws -> Int {
        guard let config = settings.serverConfiguration else { throw APIError.notConfigured }
        let api = APIClient(config: config)
        let created = try await api.selftest(preset: settings.preset)
        let job = LocalJob(assetIDs: [], phase: .processing, isSelfTest: true)
        job.serverJobID = created.id
        store.insert(job)
        store.save()
        for _ in 0 ..< 90 {
            let current = try await api.job(created.id)
            if current.status == .completed {
                apply(current, to: job)
                break
            }
            if current.status == .failed {
                throw CoordinatorError.failed(current.lastError ?? "El servidor no pudo renderizar la prueba.")
            }
            try await Task.sleep(nanoseconds: 1_000_000_000)
        }
        guard job.phase == .ready else { throw CoordinatorError.timeout("El servidor tardó demasiado.") }
        _ = await downloadAndSave(job, api: api, deadline: Date().addingTimeInterval(90))
        guard job.phase == .saved || !job.savedAssetIDs.isEmpty else {
            throw CoordinatorError.failed(job.lastError ?? "No se pudo guardar la prueba en Fotos.")
        }
        guard photos.verifyFavorites(job.savedAssetIDs) else {
            throw CoordinatorError.failed("Las imágenes no aparecen como Favoritas.")
        }
        return job.savedAssetIDs.count
    }
}

/// Pide a iOS unos segundos extra para terminar el guardado si la app pasa a segundo plano.
@MainActor
final class BackgroundTaskAssertion {
    private var identifier: UIBackgroundTaskIdentifier = .invalid

    init(name: String) {
        identifier = UIApplication.shared.beginBackgroundTask(withName: name) { [weak self] in
            Task { @MainActor in self?.end() }
        }
    }

    func end() {
        guard identifier != .invalid else { return }
        UIApplication.shared.endBackgroundTask(identifier)
        identifier = .invalid
    }
}
