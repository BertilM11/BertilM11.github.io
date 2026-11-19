import Foundation
import SwiftData
import AutoGPTCore

/// Acceso a SwiftData desde el actor principal (los volúmenes son pequeños, así que
/// se filtra en memoria y se evitan predicados complejos).
@MainActor
final class JobStore {
    let container: ModelContainer
    private var context: ModelContext { container.mainContext }

    init(container: ModelContainer) {
        self.container = container
    }

    func save() {
        do {
            try context.save()
        } catch {
            AppLog.error("SwiftData save: \(error.localizedDescription)")
        }
    }

    // MARK: Trabajos

    func allJobs() -> [LocalJob] {
        let d = FetchDescriptor<LocalJob>(sortBy: [SortDescriptor(\.createdAt, order: .reverse)])
        return (try? context.fetch(d)) ?? []
    }

    func jobs(in phases: Set<JobPhase>) -> [LocalJob] {
        allJobs().filter { phases.contains($0.phase) }.sorted { $0.createdAt < $1.createdAt }
    }

    func job(id: UUID) -> LocalJob? {
        allJobs().first { $0.id == id }
    }

    func job(serverID: String) -> LocalJob? {
        allJobs().first { $0.serverJobID == serverID }
    }

    func insert(_ job: LocalJob) {
        context.insert(job)
    }

    func delete(_ job: LocalJob) {
        context.delete(job)
    }

    // MARK: Fotos procesadas

    func processedIDs() -> Set<String> {
        let all = (try? context.fetch(FetchDescriptor<ProcessedAsset>())) ?? []
        return Set(all.map(\.localIdentifier))
    }

    func markProcessed(_ ids: [String], outcome: String, jobID: UUID?) {
        let existing = processedIDs()
        for id in ids where !existing.contains(id) {
            context.insert(ProcessedAsset(localIdentifier: id, outcome: outcome, jobID: jobID))
        }
    }

    func processedCount(since date: Date?) -> Int {
        let all = (try? context.fetch(FetchDescriptor<ProcessedAsset>())) ?? []
        guard let date else { return all.count }
        return all.filter { $0.processedAt >= date }.count
    }

    // MARK: Resultados guardados

    func ownResultIDs() -> Set<String> {
        let all = (try? context.fetch(FetchDescriptor<SavedResult>())) ?? []
        return Set(all.map(\.assetLocalIdentifier))
    }

    func addSavedResult(_ r: SavedResult) {
        context.insert(r)
    }
}
