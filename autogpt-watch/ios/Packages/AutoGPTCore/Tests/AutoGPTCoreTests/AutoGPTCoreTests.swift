import XCTest
@testable import AutoGPTCore
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class PhotoSelectionTests: XCTestCase {
    let start = Date(timeIntervalSince1970: 1_000_000)

    func testExcludesBeforeSessionScreenshotsProcessedAndOwnResults() {
        let cands = [
            PhotoCandidate(id: "old", creationDate: start.addingTimeInterval(-10)),
            PhotoCandidate(id: "shot", creationDate: start.addingTimeInterval(5), isScreenshot: true),
            PhotoCandidate(id: "done", creationDate: start.addingTimeInterval(6)),
            PhotoCandidate(id: "mine", creationDate: start.addingTimeInterval(7)),
            PhotoCandidate(id: "png", creationDate: start.addingTimeInterval(8), isPNG: true),
            PhotoCandidate(id: "video", creationDate: start.addingTimeInterval(9), isImage: false),
            PhotoCandidate(id: "nodate", creationDate: nil),
            PhotoCandidate(id: "ok2", creationDate: start.addingTimeInterval(20)),
            PhotoCandidate(id: "ok1", creationDate: start.addingTimeInterval(10)),
        ]
        let r = PhotoSelectionPolicy(maxPerJob: 6).select(cands, sessionStart: start, processed: ["done"], ownResults: ["mine"])
        XCTAssertEqual(r.batches.flatMap { $0 }.map(\.id), ["ok1", "ok2"])
        let reasons = Dictionary(uniqueKeysWithValues: r.excluded.map { ($0.0.id, $0.1) })
        XCTAssertEqual(reasons["old"], .beforeSession)
        XCTAssertEqual(reasons["shot"], .screenshot)
        XCTAssertEqual(reasons["done"], .alreadyProcessed)
        XCTAssertEqual(reasons["mine"], .ownResult)
        XCTAssertEqual(reasons["png"], .ownResult)
        XCTAssertEqual(reasons["video"], .notImage)
        XCTAssertEqual(reasons["nodate"], .noDate)
    }

    func testBatchingAndDeduplication() {
        let cands = (0 ..< 8).map { PhotoCandidate(id: "p\($0)", creationDate: start.addingTimeInterval(Double($0))) }
        let r = PhotoSelectionPolicy(maxPerJob: 3).select(cands + cands, sessionStart: start, processed: [], ownResults: [])
        XCTAssertEqual(r.batches.map(\.count), [3, 3, 2])
        XCTAssertEqual(r.batches.first?.first?.id, "p0")
    }

    func testCameraMetadataHeuristic() {
        XCTAssertTrue(CameraMetadataCheck.looksLikeIPhoneCamera(make: "Apple", model: "iPhone 16 Pro", lensModel: nil))
        XCTAssertTrue(CameraMetadataCheck.looksLikeIPhoneCamera(make: "Apple", model: nil, lensModel: "iPhone 15 back camera"))
        XCTAssertFalse(CameraMetadataCheck.looksLikeIPhoneCamera(make: nil, model: nil, lensModel: nil))
        XCTAssertFalse(CameraMetadataCheck.looksLikeIPhoneCamera(make: "Canon", model: "EOS", lensModel: "iPhone"))
    }

    func testTextRelevance() {
        let p = TextRelevancePolicy(minCharacters: 10)
        XCTAssertFalse(p.isRelevant(recognizedLines: ["  -- ", "a"]))
        XCTAssertTrue(p.isRelevant(recognizedLines: ["Ejercicio 1:", "x + 2 = 5"]))
    }
}

final class PolicyTests: XCTestCase {
    func testRetryPolicy() {
        let p = RetryPolicy(maxAttempts: 3, baseDelay: 10, maxDelay: 35)
        XCTAssertEqual(p.delay(afterAttempts: 1), 10)
        XCTAssertEqual(p.delay(afterAttempts: 2), 20)
        XCTAssertEqual(p.delay(afterAttempts: 3), 35)
        XCTAssertTrue(p.canRetry(afterAttempts: 2))
        XCTAssertFalse(p.canRetry(afterAttempts: 3))
    }

    func testHTTPClassifier() {
        XCTAssertTrue(HTTPRetryClassifier.isTransient(statusCode: 503))
        XCTAssertTrue(HTTPRetryClassifier.isTransient(statusCode: 429))
        XCTAssertFalse(HTTPRetryClassifier.isTransient(statusCode: 400))
        XCTAssertFalse(HTTPRetryClassifier.isTransient(statusCode: 401))
        XCTAssertTrue(APIError.transport("x").isTransient)
        XCTAssertFalse(APIError.invalidServerURL.isTransient)
    }

    func testAutomationGateRespectsSwitch() {
        let g = AutomationGate()
        XCTAssertEqual(g.evaluate(autoModeEnabled: true, consentGiven: true, photosFullAccess: true, serverConfigured: true), .run)
        if case .skip = g.evaluate(autoModeEnabled: false, consentGiven: true, photosFullAccess: true, serverConfigured: true) {} else {
            XCTFail("debe omitirse con el modo automático apagado")
        }
        if case .skip = g.evaluate(autoModeEnabled: true, consentGiven: false, photosFullAccess: true, serverConfigured: true) {} else {
            XCTFail("debe omitirse sin consentimiento")
        }
    }

    func testJobPhaseTransitions() {
        XCTAssertTrue(JobPhase.pendingUpload.canTransition(to: .uploading))
        XCTAssertTrue(JobPhase.saving.canTransition(to: .saved))
        XCTAssertFalse(JobPhase.saved.canTransition(to: .uploading))
        XCTAssertFalse(JobPhase.noAnswer.canTransition(to: .ready))
        XCTAssertTrue(JobPhase.failed.canTransition(to: .pendingUpload))
    }

    func testResultOrdering() {
        let d = ResultOrdering.creationDates(start: Date(timeIntervalSince1970: 0), count: 3)
        XCTAssertEqual(d.map(\.timeIntervalSince1970), [0, 1, 2])
    }
}

final class APITests: XCTestCase {
    func testServerURLValidation() throws {
        XCTAssertEqual(try ServerConfiguration.normalizedBaseURL(" https://api.example.com/ ").absoluteString, "https://api.example.com")
        XCTAssertThrowsError(try ServerConfiguration.normalizedBaseURL("http://api.example.com"))
        XCTAssertThrowsError(try ServerConfiguration.normalizedBaseURL("api.example.com"))
        XCTAssertThrowsError(try ServerConfiguration(baseURLString: "https://a.com", token: "  "))
    }

    func testRequestFactory() throws {
        let f = APIRequestFactory(config: try ServerConfiguration(baseURLString: "https://a.example.com/base", token: "tok"))
        let r = f.listJobs(statuses: [.completed, .failed])
        XCTAssertEqual(r.url?.path, "/base/v1/jobs")
        XCTAssertTrue(r.url?.query?.contains("status=completed,failed") ?? false)
        XCTAssertEqual(r.value(forHTTPHeaderField: "Authorization"), "Bearer tok")
        let c = f.createJob(clientJobID: "abc-12345", boundary: "BND")
        XCTAssertEqual(c.httpMethod, "POST")
        XCTAssertEqual(c.value(forHTTPHeaderField: "Idempotency-Key"), "abc-12345")
        XCTAssertEqual(c.value(forHTTPHeaderField: "Content-Type"), "multipart/form-data; boundary=BND")
        let file = ServerFile(name: "01-a.png", kind: "answer_page", index: 1, title: "t", bytes: 1, sha256: "x",
                              url: "/v1/jobs/j1/files/01-a.png")
        XCTAssertEqual(f.download(file).url?.absoluteString, "https://a.example.com/base/v1/jobs/j1/files/01-a.png")
        let ack = f.ack("j1", savedNames: ["01-a.png"])
        let body = try JSONSerialization.jsonObject(with: ack.httpBody!) as? [String: [String]]
        XCTAssertEqual(body?["saved"], ["01-a.png"])
    }

    func testMultipartBody() {
        let data = APIRequestFactory.createJobBody(clientJobID: "id-123456", options: JobOptions(preset: .phone),
                                                   consent: true, images: [Data([0xFF, 0xD8, 0xFF])], boundary: "B")
        let text = String(decoding: data, as: UTF8.self)
        XCTAssertTrue(text.hasPrefix("--B\r\n"))
        XCTAssertTrue(text.contains("name=\"consent\"\r\n\r\ntrue\r\n"))
        XCTAssertTrue(text.contains("name=\"preset\"\r\n\r\nphone\r\n"))
        XCTAssertTrue(text.contains("filename=\"photo-01.jpg\""))
        XCTAssertTrue(text.hasSuffix("--B--\r\n"))
    }

    func testDecodeServerJob() throws {
        let json = """
        {"id":"j1","client_job_id":"c1","status":"completed","created_at":1.5,"updated_at":2,"attempts":1,
         "image_count":2,"last_error":null,"title":"T","relevant":true,"files":[
         {"name":"02-imagen-1.png","kind":"visual","index":1,"title":"G","bytes":10,"sha256":"a","url":"/v1/jobs/j1/files/02-imagen-1.png"},
         {"name":"01-respuesta-1de1.png","kind":"answer_page","index":1,"title":"T","bytes":10,"sha256":"b","url":"/v1/jobs/j1/files/01-respuesta-1de1.png"}],
         "completed_at":3,"acked_at":null,"duplicate":false}
        """
        let job = try JSONDecoder().decode(ServerJob.self, from: Data(json.utf8))
        XCTAssertEqual(job.status, .completed)
        XCTAssertEqual(job.orderedFiles.map(\.name), ["01-respuesta-1de1.png", "02-imagen-1.png"])
        XCTAssertEqual(JobPhase.from(server: job), .ready)
        let unknown = try JSONDecoder().decode(ServerJob.self, from: Data(json.replacingOccurrences(of: "\"completed\"", with: "\"nuevo\"").utf8))
        XCTAssertEqual(unknown.status, .unknown)
    }

    func testErrorBodyParsing() {
        let e = APIError.fromResponse(status: 429, body: Data("{\"detail\":\"Límite\"}".utf8))
        XCTAssertEqual(e, .http(status: 429, detail: "Límite"))
        XCTAssertTrue(e.isTransient)
    }
}
