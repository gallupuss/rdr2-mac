// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "RDR2Mac",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "RDR2Mac", targets: ["RDR2Mac"])],
    targets: [.executableTarget(name: "RDR2Mac")],
    swiftLanguageModes: [.v5]
)
