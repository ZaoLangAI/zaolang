import ZaolangKit

/// 发现栈内的 push 目的地。`.searchResults` 由 `.searchable` 提交后 push，不是 sheet，也不是行内结果区。
enum DiscoverRoute: Hashable {
    case searchResults(query: String)
    case workDetail(workID: String)
    case lineage(workID: String)
    case profile(handle: String)
}

/// 学习栈内的 push 目的地。`workDetail` / `lineage` / `profile` 与 `DiscoverRoute` 里的同名 case
/// 故意不复用——学习栈的"查看示例作品"链路（`LearnView` 安全区块）只在学习栈内部转，
/// 不跨到发现 Tab，两个栈各自持有一份路由类型，互不牵连（没有明确列出的跳转就不切 Tab）。
enum LearnRoute: Hashable {
    case course(index: Int)
    case workDetail(workID: String)
    case lineage(workID: String)
    case profile(handle: String)
}

/// 工作台的入参：一个界面两种形态，靠 case 区分，不拆成两个 View（`roadmap.md` D3/D4 约束）。
enum StudioMode: Hashable {
    case new(operation: Operation, initialPrompt: String?)
    case remix(sourceWorkID: String)
}

/// 创作 Tab 栈内的 push 目的地。
enum CreateRoute: Hashable {
    case studio(StudioMode)
    case draft(draftID: String)
    case jobDetail(jobID: String)
    case publish(draftID: String)
    case workDetail(workID: String)
    case lineage(workID: String)
    case profile(handle: String)
}

/// 我的库栈内的 push 目的地。设置 / 通知 / 账单都挂在这一栈下——iOS 没有独立的"账号" Tab，
/// 入口统一放在我的库顶部工具栏（`LibraryView`）。
enum LibraryRoute: Hashable {
    case workDetail(workID: String)
    case lineage(workID: String)
    case profile(handle: String)
    case jobDetail(jobID: String)
    case settings
    case notifications
    case billing
}
