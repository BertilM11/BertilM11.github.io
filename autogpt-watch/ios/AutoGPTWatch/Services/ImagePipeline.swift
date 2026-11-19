import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers
import Vision
import AutoGPTCore

struct PreparedImage {
    /// JPEG reducido (máx. 2048 px) SIN metadatos EXIF/GPS: es lo único que sale del iPhone.
    let jpeg: Data
    let cgImage: CGImage
    let looksLikeCameraPhoto: Bool
}

enum ImagePipelineError: LocalizedError {
    case unreadable
    case encodeFailed

    var errorDescription: String? {
        switch self {
        case .unreadable: return "Formato de imagen no legible"
        case .encodeFailed: return "No se pudo convertir la foto a JPEG"
        }
    }
}

enum ImagePipeline {
    /// Decodifica HEIC/JPEG, aplica la orientación, reduce y recodifica a JPEG.
    static func prepare(_ data: Data, maxPixelSize: Int = 2048, quality: Double = 0.85) throws -> PreparedImage {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { throw ImagePipelineError.unreadable }
        let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any] ?? [:]
        let tiff = props[kCGImagePropertyTIFFDictionary] as? [CFString: Any]
        let exif = props[kCGImagePropertyExifDictionary] as? [CFString: Any]
        let isCamera = CameraMetadataCheck.looksLikeIPhoneCamera(
            make: tiff?[kCGImagePropertyTIFFMake] as? String,
            model: tiff?[kCGImagePropertyTIFFModel] as? String,
            lensModel: exif?[kCGImagePropertyExifLensModel] as? String
        )
        let thumbOptions: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixelSize,
        ]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, thumbOptions as CFDictionary) else {
            throw ImagePipelineError.unreadable
        }
        let output = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(output as CFMutableData, UTType.jpeg.identifier as CFString, 1, nil) else {
            throw ImagePipelineError.encodeFailed
        }
        CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { throw ImagePipelineError.encodeFailed }
        return PreparedImage(jpeg: output as Data, cgImage: image, looksLikeCameraPhoto: isCamera)
    }

    /// Reconocimiento de texto local con Vision (no sale nada del dispositivo).
    static func recognizeText(in image: CGImage) async throws -> [String] {
        try await Task.detached(priority: .userInitiated) {
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .fast
            request.usesLanguageCorrection = false
            let handler = VNImageRequestHandler(cgImage: image, options: [:])
            try handler.perform([request])
            return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
        }.value
    }
}
