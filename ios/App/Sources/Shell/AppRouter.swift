import Observation
import SwiftUI

/// 四个 Tab 各自独立的导航栈状态，全放在一处方便深链接与「二创/学习结课切 Tab」这类
/// 跨栈跳转统一操作。
@Observable
final class AppRouter {
    var selectedTab: AppTab = .discover

    var discoverPath = NavigationPath()
    var learnPath = NavigationPath()
    var createPath = NavigationPath()
    var libraryPath = NavigationPath()

    /// 当前 Tab 再被点一次 → 回到该栈根部；否则只是切 Tab。原生 `TabView` 不会为
    /// 「重复点同一个 Tab」发事件，所以底部栏用自定义按钮而不是 `.tabItem`（见 `RootTabView`）。
    func selectTab(_ tab: AppTab) {
        guard selectedTab == tab else {
            selectedTab = tab
            return
        }
        switch tab {
        case .discover: discoverPath = NavigationPath()
        case .learn: learnPath = NavigationPath()
        case .create: createPath = NavigationPath()
        case .library: libraryPath = NavigationPath()
        }
    }

    /// Universal Link 落点。冷启动时 `RootView` 先等 `bootstrap()` 完成再解析，
    /// 避免需要登录态才能判断归属的链接被误判。
    func handle(_ link: DeepLink) {
        switch link {
        case .discoverRoot:
            selectedTab = .discover
            discoverPath = NavigationPath()
        case .workDetail(let workID):
            selectedTab = .discover
            discoverPath = NavigationPath()
            discoverPath.append(DiscoverRoute.workDetail(workID: workID))
        case .profile(let handle):
            selectedTab = .discover
            discoverPath = NavigationPath()
            discoverPath.append(DiscoverRoute.profile(handle: handle))
        case .learnRoot:
            selectedTab = .learn
            learnPath = NavigationPath()
        case .createRoot:
            selectedTab = .create
            createPath = NavigationPath()
        case .jobDetail(let jobID):
            selectedTab = .create
            createPath = NavigationPath()
            createPath.append(CreateRoute.jobDetail(jobID: jobID))
        }
    }
}
