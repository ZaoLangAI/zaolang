import SwiftUI
import ZaolangKit

/// 学习栈根屏，对应 `(site)/learn/page.tsx`：Hero + 三门课卡 + 创作者安全区块。
/// 这屏在 `04-screens.md` 没有专门线框（该文档 15 屏聚焦发现/详情/图谱/主页那条主线），
/// 结构与文案直接照抄 Web 页面源码，保真度比复述线框更高。
struct LearnView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router
    @Binding var path: NavigationPath

    @State private var viewModel: LearnViewModel?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                hero
                pathsSection
                safetySection
            }
            .padding(16)
        }
        .navigationTitle(L10n.t("nav.learn"))
        .task {
            if viewModel == nil {
                viewModel = LearnViewModel(apiClient: environment.apiClient)
            }
            await viewModel?.load()
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 0) {
            RemoteImage(url: viewModel?.heroCover()?.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0, contentMode: .fill)
                .zlCornerRadius(ZLRadius.md)

            VStack(alignment: .leading, spacing: 10) {
                Text(L10n.t("learnPage.eyebrow")).zlEyebrow()
                Text(L10n.t("learnPage.heroTitle")).font(.title2.weight(.bold))
                Text(L10n.t("learnPage.heroSubtitle"))
                    .font(.subheadline)
                    .foregroundStyle(Color.zl.textMuted)

                Button {
                    router.selectTab(.create)
                } label: {
                    Label(L10n.t("learnPage.startFirst"), systemImage: "sparkles")
                }
                .buttonStyle(.borderedProminent)
            }
            .padding(.top, 16)
        }
    }

    private var pathsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(L10n.t("learnPage.paths")).font(.headline)
                Text(L10n.t("learnPage.pathsHint")).font(.caption).foregroundStyle(Color.zl.textMuted)
            }

            ForEach(Array(CourseCatalog.courses.enumerated()), id: \.element.id) { position, course in
                Button {
                    path.append(LearnRoute.course(index: course.index))
                } label: {
                    CourseCardView(course: course, cover: viewModel?.courseCover(at: position))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var safetySection: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "shield.fill")
                .foregroundStyle(Color.zl.amber)
                .frame(width: 36, height: 36)
                .background(Color.zl.amber.opacity(0.15))
                .zlCornerRadius(ZLRadius.sm)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4) {
                Text(L10n.t("learnPage.safetyEyebrow")).zlEyebrow()
                Text(L10n.t("learnPage.safetyTitle")).font(.headline)
                Text(L10n.t("learnPage.safetyBody"))
                    .font(.footnote)
                    .foregroundStyle(Color.zl.textMuted)

                if let example = viewModel?.exampleWork() {
                    Button(L10n.t("learnPage.viewExample")) {
                        path.append(LearnRoute.workDetail(workID: example.id))
                    }
                    .buttonStyle(.bordered)
                    .padding(.top, 4)
                }
            }
        }
        .padding(16)
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }
}

private struct CourseCardView: View {
    let course: CourseInfo
    let cover: WorkSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            RemoteImage(url: cover?.coverURL.flatMap(URL.init), aspectRatio: 16.0 / 9.0, contentMode: .fill)
                .overlay(alignment: .bottomTrailing) {
                    Text(formattedDuration)
                        .font(.system(size: 11, design: .monospaced))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.zl.surface.opacity(0.85))
                        .zlCornerRadius(ZLRadius.sm)
                        .padding(6)
                }

            VStack(alignment: .leading, spacing: 4) {
                Text(L10n.t(course.levelKey)).font(.caption2.weight(.medium)).foregroundStyle(Color.zl.amber)
                Text(L10n.t(course.titleKey)).font(.subheadline.weight(.semibold)).foregroundStyle(Color.zl.text)
                Text(L10n.t(course.descKey)).font(.caption).foregroundStyle(Color.zl.textMuted).lineLimit(2)
                Text("\(L10n.t("learnPage.lesson", ["index": course.index])) · \(L10n.t("learnPage.includesPractice"))")
                    .font(.caption2)
                    .foregroundStyle(Color.zl.textMuted)
            }
            .padding(12)
        }
        .background(Color.zl.surface)
        .zlCornerRadius(ZLRadius.md)
    }

    private var formattedDuration: String {
        let minutes = course.seconds / 60
        let seconds = course.seconds % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }
}
