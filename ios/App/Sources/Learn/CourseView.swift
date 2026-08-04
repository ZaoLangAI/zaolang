import SwiftUI
import ZaolangKit

/// 课程详情，`LearnView` 根 push 进来。课程内容本地静态（标题/难度/简介三行，与 Web
/// 首页卡片同源），结课 CTA 切到创作 Tab（`03-information-architecture.md` 学习栈）。
/// 插图复用同一条"社区精选可二创作品"查询，不额外建后端课程端点。
struct CourseView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    let courseIndex: Int
    let onOpenWork: (String) -> Void

    @State private var example: WorkSummary?
    @State private var loaded = false

    private var course: CourseInfo? { CourseCatalog.course(at: courseIndex) }

    var body: some View {
        ScrollView {
            if let course {
                VStack(alignment: .leading, spacing: 16) {
                    RemoteImage(url: example?.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0, contentMode: .fill)
                        .zlCornerRadius(ZLRadius.md)

                    Text(L10n.t(course.levelKey)).font(.caption.weight(.medium)).foregroundStyle(Color.zl.amber)
                    Text(L10n.t(course.titleKey)).font(.title3.weight(.semibold))
                    Text(L10n.t(course.descKey)).font(.subheadline).foregroundStyle(Color.zl.textMuted)
                    Text("\(L10n.t("learnPage.lesson", ["index": course.index])) · \(L10n.t("learnPage.includesPractice"))")
                        .font(.caption)
                        .foregroundStyle(Color.zl.textMuted)

                    if let example {
                        Button {
                            onOpenWork(example.id)
                        } label: {
                            Label(L10n.t("learnPage.viewExample"), systemImage: "play.rectangle")
                        }
                        .buttonStyle(.bordered)
                    }

                    Divider().padding(.vertical, 8)

                    Button {
                        router.selectTab(.create)
                    } label: {
                        Label(L10n.t("learnPage.startFirst"), systemImage: "sparkles")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding(16)
            }
        }
        .navigationTitle(course.map { L10n.t($0.titleKey) } ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadExample() }
    }

    private func loadExample() async {
        guard !loaded else { return }
        loaded = true
        let position = courseIndex - 1
        do {
            let items = try await environment.apiClient.listWorks(.init(remixable: true, sort: .popular, limit: 4)).items
            example = items.indices.contains(position) ? items[position] : items.first
        } catch {
            example = nil
        }
    }
}
