import SwiftUI

/// 按封面真实宽高比占位的图片视图：骨架/占位阶段就撑出 `aspectRatio`，
/// 内容到达后不跳版（`04-screens.md` 全局状态规范：loading 必须占据真实高度）。
struct RemoteImage: View {
    let url: URL?
    var aspectRatio: Double = 1
    var contentMode: ContentMode = .fill

    @State private var image: UIImage?
    @State private var failed = false

    /// 显式写这个 init，只暴露三个真正的入参——不写的话编译器合成的逐一成员初始化器会把
    /// `image` / `failed` 这两个内部加载状态也变成可传参数，调用方本不该能摆弄它们。
    init(url: URL?, aspectRatio: Double = 1, contentMode: ContentMode = .fill) {
        self.url = url
        self.aspectRatio = aspectRatio
        self.contentMode = contentMode
    }

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(contentMode: contentMode)
            } else if failed {
                RoundedRectangle.zl(ZLRadius.sm)
                    .fill(Color.zl.surfaceSoft)
                    .overlay {
                        Image(systemName: "photo")
                            .foregroundStyle(Color.zl.textMuted)
                    }
            } else {
                RoundedRectangle.zl(ZLRadius.sm)
                    .fill(Color.zl.skeleton)
                    .zlSkeletonPulse()
            }
        }
        .aspectRatio(aspectRatio, contentMode: .fit)
        .clipped()
        // 后端没有给图片配 alt 文案，周围总有标题/作者名兜底语境，这里标成装饰性、
        // 别让 VoiceOver 念出一句没信息量的"图像"。
        .accessibilityHidden(true)
        .task(id: url) { await load() }
    }

    private func load() async {
        guard let url else {
            failed = true
            return
        }
        if let cached = RemoteImageLoader.shared.cached(url) {
            image = cached
            return
        }
        failed = false
        image = nil
        do {
            image = try await RemoteImageLoader.shared.load(url)
        } catch {
            failed = true
        }
    }
}
