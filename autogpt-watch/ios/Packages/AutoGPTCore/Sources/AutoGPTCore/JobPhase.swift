import Foundation

/// Ciclo de vida local de un trabajo en el iPhone. Persistido como texto en SwiftData,
/// de modo que cualquier ejecución (Atajo, push, refresco en segundo plano o apertura
/// de la app) puede retomar el trabajo donde quedó.
public enum JobPhase: String, Codable, Sendable, CaseIterable {
    /// Fotos preparadas y cuerpo multipart escrito en disco; falta iniciar la subida.
    case pendingUpload
    /// Subida en curso (URLSession en segundo plano).
    case uploading
    /// El servidor aceptó el trabajo y lo está procesando.
    case processing
    /// Resultados listos en el servidor; falta descargarlos/guardarlos.
    case ready
    /// Descargando archivos.
    case downloading
    /// Guardando en Fotos.
    case saving
    /// Todo guardado en Fotos como Favorito y confirmado al servidor.
    case saved
    /// La IA indicó que las fotos no contenían ejercicios/documentos.
    case noAnswer
    /// Fallo recuperable: se reintentará automáticamente.
    case retryWait
    /// Fallo definitivo: requiere acción del usuario (reintentar o descartar).
    case failed

    public var displayName: String {
        switch self {
        case .pendingUpload: return "Pendiente de envío"
        case .uploading: return "Enviando"
        case .processing: return "Procesando en el servidor"
        case .ready: return "Listo para guardar"
        case .downloading: return "Descargando"
        case .saving: return "Guardando en Fotos"
        case .saved: return "Guardado"
        case .noAnswer: return "Sin ejercicios detectados"
        case .retryWait: return "Reintentando"
        case .failed: return "Error"
        }
    }

    public var isTerminal: Bool { self == .saved || self == .noAnswer }
    public var isPending: Bool { !isTerminal && self != .failed }

    /// Transiciones permitidas. Evita, por ejemplo, volver a subir un trabajo ya guardado.
    public func canTransition(to next: JobPhase) -> Bool {
        if next == self { return true }
        switch self {
        case .pendingUpload: return [.uploading, .retryWait, .failed, .processing, .ready, .noAnswer].contains(next)
        case .uploading: return [.pendingUpload, .processing, .ready, .noAnswer, .retryWait, .failed, .saved].contains(next)
        case .processing: return [.ready, .noAnswer, .retryWait, .failed, .saved].contains(next)
        case .ready: return [.downloading, .saving, .retryWait, .failed, .noAnswer, .saved].contains(next)
        case .downloading: return [.ready, .saving, .retryWait, .failed, .saved].contains(next)
        case .saving: return [.ready, .saved, .retryWait, .failed].contains(next)
        case .retryWait:
            return [.pendingUpload, .uploading, .processing, .ready, .downloading, .saving, .failed, .noAnswer, .saved].contains(next)
        case .failed: return [.pendingUpload, .processing, .ready, .noAnswer, .saved].contains(next) // reintento manual
        case .saved, .noAnswer: return false // estados finales: nunca se vuelve a subir ni guardar
        }
    }

    /// Fase local correspondiente a un estado del servidor.
    public static func from(server job: ServerJob) -> JobPhase {
        switch job.status {
        case .queued, .processing: return .processing
        case .completed:
            if job.relevant == false || job.files.isEmpty { return .noAnswer }
            return .ready
        case .acknowledged: return .saved
        case .failed: return .failed
        case .expired: return .failed
        case .unknown: return .processing
        }
    }
}

/// Fechas de creación crecientes para que las imágenes aparezcan en orden en Fotos
/// y en el álbum Favoritos del Apple Watch.
public enum ResultOrdering {
    public static func creationDates(start: Date, count: Int, step: TimeInterval = 1) -> [Date] {
        (0 ..< max(0, count)).map { start.addingTimeInterval(Double($0) * step) }
    }
}
