// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TscribeMac",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "tscribe-native", targets: ["TscribeMac"])],
    targets: [
        .executableTarget(name: "TscribeMac"),
        .testTarget(name: "TscribeMacTests", dependencies: ["TscribeMac"]),
    ]
)
