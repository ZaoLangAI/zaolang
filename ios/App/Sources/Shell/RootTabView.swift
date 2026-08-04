import SwiftUI
import ZaolangKit

/// 四个 Tab 各自的 `NavigationStack` 用 `opacity`/`allowsHitTesting` 同时保留在视图树里，
/// 而不是用原生 `TabView` 切换——原生 `TabView` 不会为"再点一次当前 Tab"发事件，
/// 没法做"回到栈根"，所以底部栏换成自定义按钮，行为交给 `AppRouter.selectTab`。
struct RootTabView: View {
    @Environment(AppEnvironment.self) private var environment
    @Environment(AppRouter.self) private var router

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                discoverStack.tabLayer(visible: router.selectedTab == .discover)
                createStack.tabLayer(visible: router.selectedTab == .create)
                learnStack.tabLayer(visible: router.selectedTab == .learn)
                libraryStack.tabLayer(visible: router.selectedTab == .library)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            if environment.reachability.isOffline {
                OfflineBanner()
            }

            bottomBar
        }
        .ignoresSafeArea(.keyboard)
    }

    /// 手动拼 `Binding` 而不是 `@Bindable`：`router` 是通过 `@Environment` 拿到的引用，
    /// 直接读写它的属性即可触发 Observation 更新，不需要额外的绑定包装。
    private var discoverPathBinding: Binding<NavigationPath> {
        Binding(get: { router.discoverPath }, set: { router.discoverPath = $0 })
    }

    private var learnPathBinding: Binding<NavigationPath> {
        Binding(get: { router.learnPath }, set: { router.learnPath = $0 })
    }

    private var createPathBinding: Binding<NavigationPath> {
        Binding(get: { router.createPath }, set: { router.createPath = $0 })
    }

    private var libraryPathBinding: Binding<NavigationPath> {
        Binding(get: { router.libraryPath }, set: { router.libraryPath = $0 })
    }

    @MainActor private var discoverStack: some View {
        NavigationStack(path: discoverPathBinding) {
            DiscoverView(path: discoverPathBinding, apiClient: environment.apiClient)
                .navigationDestination(for: DiscoverRoute.self) { route in
                    discoverDestination(route)
                }
        }
    }

    @MainActor private var learnStack: some View {
        NavigationStack(path: learnPathBinding) {
            LearnView(path: learnPathBinding)
                .navigationDestination(for: LearnRoute.self) { route in
                    learnDestination(route)
                }
        }
    }

    @MainActor private var createStack: some View {
        NavigationStack(path: createPathBinding) {
            CreateView(path: createPathBinding, apiClient: environment.apiClient)
                .navigationDestination(for: CreateRoute.self) { route in
                    createDestination(route)
                }
        }
    }

    @MainActor private var libraryStack: some View {
        NavigationStack(path: libraryPathBinding) {
            LibraryView(path: libraryPathBinding)
                .navigationDestination(for: LibraryRoute.self) { route in
                    libraryDestination(route)
                }
        }
    }

    @ViewBuilder
    private func discoverDestination(_ route: DiscoverRoute) -> some View {
        switch route {
        case .searchResults(let query):
            SearchResultsView(
                query: query,
                apiClient: environment.apiClient,
                onOpenWork: { router.discoverPath.append(DiscoverRoute.workDetail(workID: $0)) },
                onOpenAuthor: { router.discoverPath.append(DiscoverRoute.profile(handle: $0)) }
            )
        case .workDetail(let workID):
            WorkDetailView(
                workID: workID,
                onOpenLineage: { router.discoverPath.append(DiscoverRoute.lineage(workID: $0)) },
                onOpenAuthor: { router.discoverPath.append(DiscoverRoute.profile(handle: $0)) },
                onOpenWork: { router.discoverPath.append(DiscoverRoute.workDetail(workID: $0)) },
                onRemix: { startRemix(sourceWorkID: $0) }
            )
        case .lineage(let workID):
            LineageGraphView(workID: workID) { router.discoverPath.append(DiscoverRoute.workDetail(workID: $0)) }
        case .profile(let handle):
            ProfileView(
                handle: handle,
                onOpenWork: { router.discoverPath.append(DiscoverRoute.workDetail(workID: $0)) },
                onOpenLineage: { router.discoverPath.append(DiscoverRoute.lineage(workID: $0)) }
            )
        }
    }

    @ViewBuilder
    private func learnDestination(_ route: LearnRoute) -> some View {
        switch route {
        case .course(let index):
            CourseView(courseIndex: index) { router.learnPath.append(LearnRoute.workDetail(workID: $0)) }
        case .workDetail(let workID):
            WorkDetailView(
                workID: workID,
                onOpenLineage: { router.learnPath.append(LearnRoute.lineage(workID: $0)) },
                onOpenAuthor: { router.learnPath.append(LearnRoute.profile(handle: $0)) },
                onOpenWork: { router.learnPath.append(LearnRoute.workDetail(workID: $0)) },
                onRemix: { startRemix(sourceWorkID: $0) }
            )
        case .lineage(let workID):
            LineageGraphView(workID: workID) { router.learnPath.append(LearnRoute.workDetail(workID: $0)) }
        case .profile(let handle):
            ProfileView(
                handle: handle,
                onOpenWork: { router.learnPath.append(LearnRoute.workDetail(workID: $0)) },
                onOpenLineage: { router.learnPath.append(LearnRoute.lineage(workID: $0)) }
            )
        }
    }

    @ViewBuilder
    private func createDestination(_ route: CreateRoute) -> some View {
        switch route {
        case .studio(let mode):
            StudioView(mode: mode) { jobID in
                router.createPath.append(CreateRoute.jobDetail(jobID: jobID))
            }
        case .draft(let draftID):
            DraftDetailView(
                draftID: draftID,
                onOpenJob: { router.createPath.append(CreateRoute.jobDetail(jobID: $0)) },
                onOpenPublish: { router.createPath.append(CreateRoute.publish(draftID: $0)) },
                onOpenWork: { router.createPath.append(CreateRoute.workDetail(workID: $0)) }
            )
        case .jobDetail(let jobID):
            JobDetailView(
                jobID: jobID,
                onOpenPublish: { router.createPath.append(CreateRoute.publish(draftID: $0)) },
                onSwitchToJob: { newJobID in
                    router.createPath.removeLast()
                    router.createPath.append(CreateRoute.jobDetail(jobID: newJobID))
                }
            )
        case .publish(let draftID):
            PublishView(draftID: draftID) { workID in
                router.createPath.append(CreateRoute.workDetail(workID: workID))
            }
        case .workDetail(let workID):
            WorkDetailView(
                workID: workID,
                onOpenLineage: { router.createPath.append(CreateRoute.lineage(workID: $0)) },
                onOpenAuthor: { router.createPath.append(CreateRoute.profile(handle: $0)) },
                onOpenWork: { router.createPath.append(CreateRoute.workDetail(workID: $0)) },
                onRemix: { startRemix(sourceWorkID: $0) }
            )
        case .lineage(let workID):
            LineageGraphView(workID: workID) { router.createPath.append(CreateRoute.workDetail(workID: $0)) }
        case .profile(let handle):
            ProfileView(
                handle: handle,
                onOpenWork: { router.createPath.append(CreateRoute.workDetail(workID: $0)) },
                onOpenLineage: { router.createPath.append(CreateRoute.lineage(workID: $0)) }
            )
        }
    }

    @ViewBuilder
    private func libraryDestination(_ route: LibraryRoute) -> some View {
        switch route {
        case .workDetail(let workID):
            WorkDetailView(
                workID: workID,
                onOpenLineage: { router.libraryPath.append(LibraryRoute.lineage(workID: $0)) },
                onOpenAuthor: { router.libraryPath.append(LibraryRoute.profile(handle: $0)) },
                onOpenWork: { router.libraryPath.append(LibraryRoute.workDetail(workID: $0)) },
                onRemix: { startRemix(sourceWorkID: $0) }
            )
        case .lineage(let workID):
            LineageGraphView(workID: workID) { router.libraryPath.append(LibraryRoute.workDetail(workID: $0)) }
        case .profile(let handle):
            ProfileView(
                handle: handle,
                onOpenWork: { router.libraryPath.append(LibraryRoute.workDetail(workID: $0)) },
                onOpenLineage: { router.libraryPath.append(LibraryRoute.lineage(workID: $0)) }
            )
        case .jobDetail(let jobID):
            JobDetailView(
                jobID: jobID,
                onOpenPublish: { draftID in
                    router.selectTab(.create)
                    router.createPath.append(CreateRoute.publish(draftID: draftID))
                },
                onSwitchToJob: { newJobID in
                    router.libraryPath.removeLast()
                    router.libraryPath.append(LibraryRoute.jobDetail(jobID: newJobID))
                }
            )
        case .settings:
            SettingsView()
        case .notifications:
            NotificationsView(
                onOpenWork: { router.libraryPath.append(LibraryRoute.workDetail(workID: $0)) },
                onOpenJob: { router.libraryPath.append(LibraryRoute.jobDetail(jobID: $0)) }
            )
        case .billing:
            BillingView()
        }
    }

    /// 二创统一入口：不管从哪个 Tab 的作品详情点"二创"，都切到创作 Tab 并把工作台压进
    /// 创作栈——`roadmap.md` 里"二创只有一份表单状态"的约束意味着它只能属于一个栈。
    private func startRemix(sourceWorkID: String) {
        router.selectTab(.create)
        router.createPath.append(CreateRoute.studio(.remix(sourceWorkID: sourceWorkID)))
    }

    private var bottomBar: some View {
        HStack(spacing: 0) {
            ForEach(AppTab.allCases) { tab in
                Button {
                    router.selectTab(tab)
                } label: {
                    VStack(spacing: 3) {
                        Image(systemName: tab.systemImage)
                            .font(.system(size: 20))
                        Text(L10n.t(tab.titleKey))
                            .font(.system(size: 11))
                    }
                    .foregroundStyle(router.selectedTab == tab ? Color.zl.primary : Color.zl.textMuted)
                    .frame(maxWidth: .infinity)
                }
                .accessibilityAddTraits(router.selectedTab == tab ? [.isSelected] : [])
            }
        }
        .padding(.top, 8)
        .padding(.bottom, 4)
        .background(.bar)
    }
}

private extension View {
    /// 四个 Tab 内容同时挂在视图树上以保留各自状态，只有当前选中的可见、可交互。
    func tabLayer(visible: Bool) -> some View {
        opacity(visible ? 1 : 0)
            .allowsHitTesting(visible)
            .accessibilityHidden(!visible)
    }
}
