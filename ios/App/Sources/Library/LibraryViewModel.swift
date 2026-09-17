import Observation
import ZaolangKit

/// 我的库四个分段各自独立加载、独立失败——收藏拉不到不该连累作品列表也显示错误态。
enum LibrarySegment: String, CaseIterable, Identifiable {
    case works
    case drafts
    case bookmarks
    case collections

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .works: "collectionPage.tabAll"
        case .drafts: "collectionPage.tabDrafts"
        case .bookmarks: "collectionPage.tabBookmarks"
        case .collections: "collectionPage.collections"
        }
    }
}

@MainActor
@Observable
final class LibraryViewModel {
    private let apiClient: APIClient

    private(set) var worksState: LoadableState<[WorkSummary]> = .loading
    private(set) var draftsState: LoadableState<[DraftResponse]> = .loading
    private(set) var bookmarksState: LoadableState<[WorkSummary]> = .loading
    private(set) var collectionsState: LoadableState<[CollectionResponse]> = .loading
    private(set) var unreadCount = 0

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    /// 四段各自 `try?` 独立失败；`handle` 为 nil（`me.profile` 还没拉到）时四段都直接判空，
    /// 不整屏报错——`LibraryView` 只在 `environment.isAuthenticated` 为真时才会挂载这个 VM。
    func load(handle: String?) async {
        async let works: () = loadWorks(handle: handle)
        async let drafts: () = loadDrafts()
        async let bookmarks: () = loadBookmarks()
        async let collections: () = loadCollections()
        async let unread: () = loadUnreadCount()
        _ = await (works, drafts, bookmarks, collections, unread)
    }

    private func loadWorks(handle: String?) async {
        guard let handle else {
            worksState = .empty
            return
        }
        do {
            let page = try await apiClient.profileWorks(handle: handle, limit: 60)
            worksState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            worksState = .failed(error)
        } catch {
            worksState = .failed(.unexpectedResponse(status: 0))
        }
    }

    private func loadDrafts() async {
        do {
            let page = try await apiClient.listDrafts(limit: 50)
            draftsState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            draftsState = .failed(error)
        } catch {
            draftsState = .failed(.unexpectedResponse(status: 0))
        }
    }

    private func loadBookmarks() async {
        do {
            let page = try await apiClient.myBookmarks(limit: 60)
            bookmarksState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            bookmarksState = .failed(error)
        } catch {
            bookmarksState = .failed(.unexpectedResponse(status: 0))
        }
    }

    private func loadCollections() async {
        do {
            let page = try await apiClient.listCollections(limit: 30)
            collectionsState = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            collectionsState = .failed(error)
        } catch {
            collectionsState = .failed(.unexpectedResponse(status: 0))
        }
    }

    private func loadUnreadCount() async {
        unreadCount = (try? await apiClient.unreadNotificationCount().count) ?? 0
    }

    func createCollection(name: String, isPublic: Bool) async {
        guard !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        do {
            let created = try await apiClient.createCollection(CollectionCreateRequest(name: name, isPublic: isPublic))
            if case .loaded(var items) = collectionsState {
                items.insert(created, at: 0)
                collectionsState = .loaded(items)
            } else {
                collectionsState = .loaded([created])
            }
        } catch {
            // 建合集失败不阻塞其余分段，静默保留原状态，用户可以重开表单重试。
        }
    }

    func deleteDraft(id: String) async {
        do {
            try await apiClient.deleteDraft(id: id)
            if case .loaded(let items) = draftsState {
                let remaining = items.filter { $0.id != id }
                draftsState = remaining.isEmpty ? .empty : .loaded(remaining)
            }
        } catch {
            // 删除失败静默保留原状态，用户从列表里仍能看到这条草稿并重试删除。
        }
    }
}
