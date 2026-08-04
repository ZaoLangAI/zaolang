import ZaolangKit

/// 屏幕/区块通用的加载态。`offline` 与「未登录」是叠加在这个状态之上的横向维度，不并进
/// 这个枚举——一个作品详情可以同时是 `.loaded` 又叠一条离线横幅。
enum LoadableState<Value> {
    case loading
    case loaded(Value)
    case empty
    case failed(ApiError)
}

extension LoadableState {
    var value: Value? {
        if case .loaded(let value) = self { return value }
        return nil
    }

    var isLoading: Bool {
        if case .loading = self { return true }
        return false
    }
}
