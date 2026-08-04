import Observation
import ZaolangKit

/// 发现页的状态与请求编排：Hero（`works?limit=1&sort=popular`）、标签、
/// 双列瀑布墙的游标翻页，三者互相独立、可以各自失败各自重试。
@MainActor
@Observable
final class DiscoverViewModel {
    private let apiClient: APIClient

    private(set) var heroState: LoadableState<WorkSummary> = .loading
    private(set) var tagsState: LoadableState<[TagResponse]> = .loading
    private(set) var feedState: LoadableState<[WorkSummary]> = .loading

    var selectedTag: String?
    var sort: WorksSort = .recent
    var remixableOnly = false

    private var items: [WorkSummary] = []
    private var nextCursor: String?
    private var hasMore = true
    private(set) var isLoadingMore = false

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func loadInitial() async {
        async let hero: Void = loadHero()
        async let tags: Void = loadTags()
        async let feed: Void = loadFeed(reset: true)
        _ = await (hero, tags, feed)
    }

    func refresh() async {
        async let hero: Void = loadHero()
        async let feed: Void = loadFeed(reset: true)
        _ = await (hero, feed)
    }

    func loadHero() async {
        heroState = .loading
        do {
            let page = try await apiClient.listWorks(.init(remixable: false, sort: .popular, limit: 1))
            heroState = page.items.first.map { .loaded($0) } ?? .empty
        } catch let error as ApiError {
            heroState = .failed(error)
        } catch {
            heroState = .failed(.unexpectedResponse(status: 0))
        }
    }

    func loadTags() async {
        tagsState = .loading
        do {
            let page = try await apiClient.listTags()
            tagsState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            tagsState = .failed(error)
        } catch {
            tagsState = .failed(.unexpectedResponse(status: 0))
        }
    }

    /// `reset: true` 用于首次加载、下拉刷新、切换排序/标签/筛选；`false` 用于滚到底部翻页。
    func loadFeed(reset: Bool) async {
        if reset {
            items = []
            nextCursor = nil
            hasMore = true
            feedState = .loading
        }
        guard hasMore else { return }
        isLoadingMore = !reset
        defer { isLoadingMore = false }

        do {
            let query = APIClient.WorksQuery(
                tag: selectedTag,
                remixable: remixableOnly,
                sort: sort,
                cursor: reset ? nil : nextCursor,
                limit: 24
            )
            let page = try await apiClient.listWorks(query)
            items.append(contentsOf: page.items)
            nextCursor = page.nextCursor
            hasMore = page.hasMore
            feedState = items.isEmpty ? .empty : .loaded(items)
        } catch let error as ApiError {
            feedState = reset ? .failed(error) : feedState // 翻页失败保留已有内容，不清空列表
        } catch {
            feedState = reset ? .failed(.unexpectedResponse(status: 0)) : feedState
        }
    }

    /// 滚到倒数第 6 张就开始翻页，等真的到底部才请求会让用户先看到一小段空白。
    func loadMoreIfNeeded(currentItem: WorkSummary) async {
        guard hasMore, !isLoadingMore else { return }
        guard let index = items.firstIndex(where: { $0.id == currentItem.id }) else { return }
        guard index >= items.count - 6 else { return }
        await loadFeed(reset: false)
    }

    func setSort(_ sort: WorksSort) async {
        guard self.sort != sort else { return }
        self.sort = sort
        await loadFeed(reset: true)
    }

    func setTag(_ tag: String?) async {
        guard selectedTag != tag else { return }
        selectedTag = tag
        await loadFeed(reset: true)
    }

    func setRemixableOnly(_ value: Bool) async {
        guard remixableOnly != value else { return }
        remixableOnly = value
        await loadFeed(reset: true)
    }
}
