// swift-tools-version:5.9
// Lógica independiente de la plataforma (sólo Foundation): se puede probar con
// `swift test` en macOS o Linux y la usa la app iOS.
import PackageDescription

let package = Package(
    name: "AutoGPTCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "AutoGPTCore", targets: ["AutoGPTCore"]),
    ],
    targets: [
        .target(name: "AutoGPTCore"),
        .testTarget(name: "AutoGPTCoreTests", dependencies: ["AutoGPTCore"]),
    ]
)
