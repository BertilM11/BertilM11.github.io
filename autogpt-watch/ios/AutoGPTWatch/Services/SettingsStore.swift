import Combine
import Foundation
import AutoGPTCore

/// Preferencias del usuario (UserDefaults) + token del servidor (Llavero).
@MainActor
final class SettingsStore: ObservableObject {
    private enum Key {
        static let autoMode = "autoModeEnabled"
        static let sessionStart = "sessionStart"
        static let consent = "consentGivenAt"
        static let serverURL = "serverURL"
        static let preset = "preset"
        static let language = "language"
        static let illustrations = "allowIllustrations"
        static let visionFilter = "visionFilterEnabled"
        static let visionMin = "visionMinCharacters"
        static let cameraOnly = "requireCameraMetadata"
        static let album = "createAlbum"
        static let deleteUploads = "deleteUploads"
        static let notifySaved = "notifyOnSave"
        static let apnsToken = "apnsToken"
        static let apnsRegisteredFor = "apnsRegisteredFor"
    }

    nonisolated static let albumName = "AutoGPT Watch"

    private let defaults: UserDefaults
    nonisolated private static func makeKeychain() -> KeychainStore {
        KeychainStore(service: "AutoGPTWatch", account: "deviceToken")
    }

    private let keychain = SettingsStore.makeKeychain()

    @Published var autoModeEnabled: Bool { didSet { defaults.set(autoModeEnabled, forKey: Key.autoMode) } }
    @Published var sessionStart: Date? { didSet { defaults.set(sessionStart, forKey: Key.sessionStart) } }
    @Published var consentGivenAt: Date? { didSet { defaults.set(consentGivenAt, forKey: Key.consent) } }
    @Published var serverURL: String { didSet { defaults.set(serverURL, forKey: Key.serverURL) } }
    @Published var preset: ResponsePreset { didSet { defaults.set(preset.rawValue, forKey: Key.preset) } }
    @Published var language: ResponseLanguage { didSet { defaults.set(language.rawValue, forKey: Key.language) } }
    @Published var allowIllustrations: Bool { didSet { defaults.set(allowIllustrations, forKey: Key.illustrations) } }
    @Published var visionFilterEnabled: Bool { didSet { defaults.set(visionFilterEnabled, forKey: Key.visionFilter) } }
    @Published var visionMinCharacters: Int { didSet { defaults.set(visionMinCharacters, forKey: Key.visionMin) } }
    @Published var requireCameraMetadata: Bool { didSet { defaults.set(requireCameraMetadata, forKey: Key.cameraOnly) } }
    @Published var createAlbum: Bool { didSet { defaults.set(createAlbum, forKey: Key.album) } }
    @Published var deleteUploads: Bool { didSet { defaults.set(deleteUploads, forKey: Key.deleteUploads) } }
    @Published var notifyOnSave: Bool { didSet { defaults.set(notifyOnSave, forKey: Key.notifySaved) } }
    @Published var apnsToken: String? { didSet { defaults.set(apnsToken, forKey: Key.apnsToken) } }
    /// "<servidor>|<token APNs>" ya registrado, para no repetir el registro.
    @Published var apnsRegisteredFor: String? { didSet { defaults.set(apnsRegisteredFor, forKey: Key.apnsRegisteredFor) } }

    /// Sólo indica si hay token; el valor vive en el Llavero.
    @Published private(set) var hasServerToken: Bool

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        defaults.register(defaults: [
            Key.illustrations: true,
            Key.visionFilter: true,
            Key.visionMin: 20,
            Key.cameraOnly: true,
            Key.album: true,
            Key.deleteUploads: true,
            Key.notifySaved: true,
        ])
        autoModeEnabled = defaults.bool(forKey: Key.autoMode)
        sessionStart = defaults.object(forKey: Key.sessionStart) as? Date
        consentGivenAt = defaults.object(forKey: Key.consent) as? Date
        serverURL = defaults.string(forKey: Key.serverURL) ?? ""
        preset = ResponsePreset(rawValue: defaults.string(forKey: Key.preset) ?? "") ?? .watch
        language = ResponseLanguage(rawValue: defaults.string(forKey: Key.language) ?? "") ?? .spanish
        allowIllustrations = defaults.bool(forKey: Key.illustrations)
        visionFilterEnabled = defaults.bool(forKey: Key.visionFilter)
        visionMinCharacters = defaults.integer(forKey: Key.visionMin)
        requireCameraMetadata = defaults.bool(forKey: Key.cameraOnly)
        createAlbum = defaults.bool(forKey: Key.album)
        deleteUploads = defaults.bool(forKey: Key.deleteUploads)
        notifyOnSave = defaults.bool(forKey: Key.notifySaved)
        apnsToken = defaults.string(forKey: Key.apnsToken)
        apnsRegisteredFor = defaults.string(forKey: Key.apnsRegisteredFor)
        hasServerToken = SettingsStore.makeKeychain().read() != nil
    }

    var consentGiven: Bool { consentGivenAt != nil }

    var serverToken: String? { keychain.read() }

    func setServerToken(_ token: String) {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            keychain.delete()
        } else {
            keychain.write(trimmed)
        }
        hasServerToken = keychain.read() != nil
        apnsRegisteredFor = nil
    }

    /// Configuración del servidor validada, o nil si falta algo.
    var serverConfiguration: ServerConfiguration? {
        guard let token = keychain.read() else { return nil }
        return try? ServerConfiguration(baseURLString: serverURL, token: token)
    }

    var jobOptions: JobOptions {
        JobOptions(preset: preset, language: language, allowIllustrations: allowIllustrations, deleteUploads: deleteUploads)
    }
}
