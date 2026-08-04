import SwiftUI
import ZaolangKit

/// 灵感预览 sheet，对应 `components/discover/inspiration-dialog.tsx`。
/// 头部用瀑布墙已有的 `WorkSummary`立即画出来，prompt/许可/描述这些字段要等 `WorkDetail`
/// 到达才有，用骨架占着，不让整个 sheet 等一次网络往返才出现。
struct InspirationPreviewSheet: View {
    let work: WorkSummary
    let apiClient: APIClient

    /// 「用这个 prompt 创作」是纯引用（不继承来源/许可，不是二创），落点是创作 Tab 的新建
    /// 工作台并预填 prompt——调用方负责先 `requireAuth`，登录墙不在这个 sheet 内部处理。
    let onCreateFromPrompt: (String) -> Void
    let onOpenLineage: () -> Void
    let onOpenWork: () -> Void

    @State private var detailState: LoadableState<WorkDetail> = .loading

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                RemoteImage(url: work.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0)
                    .zlCornerRadius(ZLRadius.md)

                HStack(alignment: .top) {
                    AuthorRow(author: work.author, avatarSize: 32)
                    Spacer()
                    HStack(spacing: 12) {
                        StatItem(systemImage: "heart.fill", value: work.stats.likeCount, a11yLabel: L10n.t("work.likes"))
                        StatItem(systemImage: "arrow.triangle.branch", value: work.stats.remixCount, a11yLabel: L10n.t("work.remixes"))
                    }
                }

                if !work.tags.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(work.tags, id: \.self) { TagChip(label: $0) }
                        }
                    }
                }

                detailSection

                Divider()

                HStack(spacing: 12) {
                    Button {
                        onOpenLineage()
                    } label: {
                        Label(L10n.t("work.viewLineage"), systemImage: "arrow.triangle.branch")
                    }
                    .buttonStyle(.bordered)

                    Button(L10n.t("workPage.versionDetail"), action: onOpenWork)
                        .buttonStyle(.borderless)
                }
            }
            .padding(20)
        }
        .navigationTitle(work.title)
        .task { await loadDetail() }
    }

    @ViewBuilder
    private var detailSection: some View {
        switch detailState {
        case .loading:
            VStack(alignment: .leading, spacing: 8) {
                RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).frame(height: 14).zlSkeletonPulse()
                RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).frame(height: 14).frame(maxWidth: 200).zlSkeletonPulse()
                RoundedRectangle.zl(ZLRadius.sm).fill(Color.zl.skeleton).frame(height: 80).zlSkeletonPulse()
            }
        case .failed:
            Text(L10n.t("workPage.notFound"))
                .font(.footnote)
                .foregroundStyle(Color.zl.textMuted)
        case .empty:
            EmptyView()
        case .loaded(let detail):
            VStack(alignment: .leading, spacing: 12) {
                if let description = detail.description, !description.isEmpty {
                    Text(description)
                        .font(.footnote)
                        .foregroundStyle(Color.zl.textMuted)
                }

                if let license = detail.license {
                    Text(license.attributionText.isEmpty ? license.licenseType.value?.rawValue ?? "" : license.attributionText)
                        .font(.caption)
                        .foregroundStyle(Color.zl.amber)
                }

                if let prompt = detail.reusableParams?.prompt?.trimmingCharacters(in: .whitespacesAndNewlines), !prompt.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(L10n.t("discover.promptTitle"))
                            .font(.subheadline.weight(.semibold))
                        Text(L10n.t("discover.promptHint"))
                            .font(.caption)
                            .foregroundStyle(Color.zl.textMuted)
                        Text(prompt)
                            .font(.footnote)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color.zl.surface)
                            .zlCornerRadius(ZLRadius.sm)

                        Button {
                            onCreateFromPrompt(prompt)
                        } label: {
                            Label(L10n.t("discover.createFromPrompt"), systemImage: "sparkles")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    .padding(12)
                    .background(Color.zl.surfaceSoft)
                    .zlCornerRadius(ZLRadius.md)
                } else {
                    Text(L10n.t("discover.promptUnavailable"))
                        .font(.footnote)
                        .foregroundStyle(Color.zl.textMuted)
                }
            }
        }
    }

    private func loadDetail() async {
        detailState = .loading
        do {
            let detail = try await apiClient.fetchWork(id: work.id)
            detailState = .loaded(detail)
        } catch let error as ApiError {
            detailState = .failed(error)
        } catch {
            detailState = .failed(.unexpectedResponse(status: 0))
        }
    }
}
