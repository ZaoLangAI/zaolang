import SwiftUI
import ZaolangKit

/// 搜索结果屏，`.searchable` 提交后 push 到这里（对应 `04-screens.md` 第 5 屏）。
/// 线框里还有一个「语义搜索」开关，但后端 `GET /v1/works?q=` 只支持关键字匹配，没有对应参数
/// ——不做一个点了也没效果的开关，等后端真的支持再加（YAGNI）。
struct SearchResultsView: View {
    let query: String
    let apiClient: APIClient
    let onOpenWork: (String) -> Void
    let onOpenAuthor: (String) -> Void

    @State private var remixableOnly = false
    @State private var state: LoadableState<[WorkSummary]> = .loading

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            filters
            content
        }
        .padding(.top, 8)
        .navigationTitle(L10n.t("discover.resultsFor", ["query": query]))
        .navigationBarTitleDisplayMode(.inline)
        .task(id: remixableOnly) { await load() }
    }

    private var header: some View {
        Group {
            if case .loaded(let items) = state {
                Text(L10n.t("discover.results", ["count": items.count]))
            } else {
                Text(L10n.t("discover.resultsFor", ["query": query]))
            }
        }
        .font(.footnote)
        .foregroundStyle(Color.zl.textMuted)
        .padding(.horizontal, 16)
    }

    private var filters: some View {
        Toggle(L10n.t("discover.remixableOnly"), isOn: $remixableOnly)
            .fixedSize()
            .font(.footnote)
            .padding(.horizontal, 16)
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            ScrollView {
                HStack(spacing: 12) {
                    ForEach(0..<2, id: \.self) { _ in
                        VStack(spacing: 12) {
                            ForEach(0..<3, id: \.self) { _ in
                                RoundedRectangle.zl(ZLRadius.md)
                                    .fill(Color.zl.skeleton)
                                    .zlSkeletonPulse()
                                    .aspectRatio(3.0 / 4.0, contentMode: .fit)
                            }
                        }
                    }
                }
                .padding(.horizontal, 16)
            }
        case .empty:
            // 出口动作就是上面那个筛选开关本身，没有贴切的现成文案就不硬造一个按钮
            // （`actions.apply` 语义是"应用"而不是"清除筛选"，套用会误导）。
            EmptyStateView(
                title: L10n.t("discover.noResults"),
                message: L10n.t("discover.noResultsHint")
            )
        case .failed(let error):
            ErrorStateView(error: error) { Task { await load() } }
        case .loaded(let items):
            ScrollView {
                WaterfallGrid(items: items, aspectRatio: { $0.coverAspectRatio }) { work in
                    WorkCardView(
                        work: work,
                        onTapCover: { onOpenWork(work.id) },
                        onTapAuthor: { onOpenAuthor(work.author.handle) }
                    )
                }
                .padding(.horizontal, 16)
            }
        }
    }

    private func load() async {
        state = .loading
        do {
            let page = try await apiClient.listWorks(.init(q: query, remixable: remixableOnly, limit: 40))
            state = page.items.isEmpty ? .empty : .loaded(page.items)
        } catch let error as ApiError {
            state = .failed(error)
        } catch {
            state = .failed(.unexpectedResponse(status: 0))
        }
    }
}
