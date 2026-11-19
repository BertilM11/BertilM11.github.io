import Foundation
import Photos
import UniformTypeIdentifiers
import AutoGPTCore

enum PhotoLibraryError: LocalizedError {
    case notAuthorized
    case imageUnavailable(String)
    case saveFailed(String)
    case albumUnavailable

    var errorDescription: String? {
        switch self {
        case .notAuthorized: return "AutoGPT Watch no tiene acceso completo a Fotos."
        case let .imageUnavailable(msg): return "No se pudo leer la foto: \(msg)"
        case let .saveFailed(msg): return "No se pudo guardar en Fotos: \(msg)"
        case .albumUnavailable: return "No se pudo crear el álbum AutoGPT Watch."
        }
    }
}

/// Caja de referencia para recuperar identificadores creados dentro de performChanges.
private final class IdentifierBox: @unchecked Sendable {
    var values: [String] = []
}

/// Todo el acceso a PhotoKit. Lee fotos y guarda resultados; nunca modifica ni borra originales.
final class PhotoLibraryService: @unchecked Sendable {
    // MARK: Permisos

    static var authorizationStatus: PHAuthorizationStatus {
        PHPhotoLibrary.authorizationStatus(for: .readWrite)
    }

    static var hasFullAccess: Bool { authorizationStatus == .authorized }

    static func requestAccess() async -> PHAuthorizationStatus {
        await PHPhotoLibrary.requestAuthorization(for: .readWrite)
    }

    // MARK: Lectura

    /// Fotos de la fototeca del usuario creadas desde `since`, con metadatos para el filtro.
    func fetchCandidates(since: Date) -> [(asset: PHAsset, candidate: PhotoCandidate)] {
        let options = PHFetchOptions()
        options.predicate = NSPredicate(format: "mediaType == %d AND creationDate >= %@",
                                        PHAssetMediaType.image.rawValue, since as NSDate)
        options.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: true)]
        options.includeAssetSourceTypes = [.typeUserLibrary]
        let result = PHAsset.fetchAssets(with: options)
        var out: [(asset: PHAsset, candidate: PhotoCandidate)] = []
        result.enumerateObjects { asset, _, _ in
            let resources = PHAssetResource.assetResources(for: asset)
            let original = resources.first { $0.type == .photo } ?? resources.first
            let isPNG = original?.uniformTypeIdentifier == UTType.png.identifier
            let candidate = PhotoCandidate(
                id: asset.localIdentifier,
                creationDate: asset.creationDate,
                isScreenshot: asset.mediaSubtypes.contains(.photoScreenshot),
                isScreenRecording: false,
                isPNG: isPNG,
                isImage: asset.mediaType == .image
            )
            out.append((asset: asset, candidate: candidate))
        }
        return out
    }

    /// Datos originales de la foto (HEIC/JPEG). Permite descargar de iCloud si hace falta.
    func imageData(for asset: PHAsset) async throws -> Data {
        let options = PHImageRequestOptions()
        options.isNetworkAccessAllowed = true
        options.deliveryMode = .highQualityFormat
        options.version = .current
        return try await withCheckedThrowingContinuation { continuation in
            PHImageManager.default().requestImageDataAndOrientation(for: asset, options: options) { data, _, _, info in
                if let data {
                    continuation.resume(returning: data)
                } else {
                    let err = (info?[PHImageErrorKey] as? Error)?.localizedDescription ?? "sin datos"
                    continuation.resume(throwing: PhotoLibraryError.imageUnavailable(err))
                }
            }
        }
    }

    // MARK: Escritura

    /// Guarda los PNG en Fotos, los marca como Favoritos y (opcionalmente) los añade al
    /// álbum. Todo en una sola transacción: o se guardan todos o ninguno.
    /// Devuelve los localIdentifier creados, en el mismo orden.
    func saveFavorites(fileURLs: [URL], creationDates: [Date], albumName: String?) async throws -> [String] {
        guard Self.hasFullAccess else { throw PhotoLibraryError.notAuthorized }
        let album = try await albumName.asyncMap { try await self.findOrCreateAlbum(named: $0) }
        let box = IdentifierBox()
        do {
            try await PHPhotoLibrary.shared().performChanges {
                var placeholders: [PHObjectPlaceholder] = []
                for (index, url) in fileURLs.enumerated() {
                    guard let request = PHAssetChangeRequest.creationRequestForAssetFromImage(atFileURL: url) else { continue }
                    request.creationDate = index < creationDates.count ? creationDates[index] : Date()
                    request.isFavorite = true
                    if let placeholder = request.placeholderForCreatedAsset {
                        placeholders.append(placeholder)
                        box.values.append(placeholder.localIdentifier)
                    }
                }
                if let album, let albumRequest = PHAssetCollectionChangeRequest(for: album) {
                    albumRequest.addAssets(placeholders as NSArray)
                }
            }
        } catch {
            throw PhotoLibraryError.saveFailed(error.localizedDescription)
        }
        guard box.values.count == fileURLs.count else {
            throw PhotoLibraryError.saveFailed("se crearon \(box.values.count) de \(fileURLs.count) imágenes")
        }
        return box.values
    }

    /// Comprueba que los activos existen y están marcados como Favoritos.
    func verifyFavorites(_ ids: [String]) -> Bool {
        guard !ids.isEmpty else { return false }
        let result = PHAsset.fetchAssets(withLocalIdentifiers: ids, options: nil)
        guard result.count == ids.count else { return false }
        var allFavorite = true
        result.enumerateObjects { asset, _, _ in
            if !asset.isFavorite { allFavorite = false }
        }
        return allFavorite
    }

    func findOrCreateAlbum(named name: String) async throws -> PHAssetCollection {
        if let existing = fetchAlbum(named: name) { return existing }
        let box = IdentifierBox()
        try await PHPhotoLibrary.shared().performChanges {
            let request = PHAssetCollectionChangeRequest.creationRequestForAssetCollection(withTitle: name)
            box.values.append(request.placeholderForCreatedAssetCollection.localIdentifier)
        }
        guard let id = box.values.first,
              let album = PHAssetCollection.fetchAssetCollections(withLocalIdentifiers: [id], options: nil).firstObject
        else { throw PhotoLibraryError.albumUnavailable }
        return album
    }

    private func fetchAlbum(named name: String) -> PHAssetCollection? {
        let options = PHFetchOptions()
        options.predicate = NSPredicate(format: "title == %@", name)
        return PHAssetCollection.fetchAssetCollections(with: .album, subtype: .albumRegular, options: options).firstObject
    }
}

private extension Optional {
    func asyncMap<T>(_ transform: (Wrapped) async throws -> T) async rethrows -> T? {
        switch self {
        case let .some(value): return try await transform(value)
        case .none: return nil
        }
    }
}
