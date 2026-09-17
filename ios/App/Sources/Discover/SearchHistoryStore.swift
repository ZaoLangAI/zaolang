import Foundation
import Observation

/// 本地搜索历史，最近 8 条，可清空（`04-screens.md` 搜索结果屏要求）。M1 没有跨端同步，
/// 纯 `UserDefaults`，重装 App 就清空——这本来就是历史记录该有的生命周期。
@MainActor
@Observable
final class SearchHistoryStore {
    private static let key = "ai.zaolang.searchHistory"
    private static let limit = 8

    private(set) var recentQueries: [String]

    init() {
        recentQueries = UserDefaults.standard.stringArray(forKey: Self.key) ?? []
    }

    func record(_ query: String) {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        var updated = recentQueries.filter { $0 != trimmed }
        updated.insert(trimmed, at: 0)
        recentQueries = Array(updated.prefix(Self.limit))
        UserDefaults.standard.set(recentQueries, forKey: Self.key)
    }

    func clear() {
        recentQueries = []
        UserDefaults.standard.removeObject(forKey: Self.key)
    }
}
