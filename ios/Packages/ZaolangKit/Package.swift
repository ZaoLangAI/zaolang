// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "ZaolangKit",
    platforms: [
        .iOS(.v17),
        .macOS(.v13), // 仅用于本机 `swift build` 做无 Xcode 的可编译性验证，App 不会在 macOS 上运行
    ],
    products: [
        .library(name: "ZaolangKit", targets: ["ZaolangKit"])
    ],
    targets: [
        .target(name: "ZaolangKit")
    ]
)
