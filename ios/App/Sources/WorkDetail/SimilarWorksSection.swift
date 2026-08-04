import SwiftUI
import ZaolangKit

/// 对应 `components/work/work-card.tsx` 在详情页底部的横向铺排（"相似作品"）。
struct SimilarWorksSection: View {
    let state: LoadableState<[WorkSummary]>
    let onOpenWork: (String) -> Void
    let onOpenAuthor: (String) -> Void

    var body: some View {
        switch state {
        case .loading:
            VStack(alignment: .leading, spacing: 12) {
                header
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(0..<4, id: \.self) { _ in
                            RoundedRectangle.zl(ZLRadius.md)
                                .fill(Color.zl.skeleton)
                                .zlSkeletonPulse()
                                .frame(width: 120, height: 120)
                        }
                    }
                }
            }
        case .empty:
            VStack(alignment: .leading, spacing: 8) {
                header
                Text(L10n.t("workPage.similarEmpty"))
                    .font(.footnote)
                    .foregroundStyle(Color.zl.textMuted)
            }
        case .failed:
            EmptyView() // 相似作品不是这屏的主内容，失败就整体隐藏，不占位打扰阅读详情
        case .loaded(let items):
            VStack(alignment: .leading, spacing: 12) {
                header
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(items) { work in
                            WorkCardView(
                                work: work,
                                onTapCover: { onOpenWork(work.id) },
                                onTapAuthor: { onOpenAuthor(work.author.handle) }
                            )
                            .frame(width: 140)
                        }
                    }
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(L10n.t("workPage.relatedTitle")).font(.subheadline.weight(.semibold))
            Text(L10n.t("workPage.relatedHint")).font(.caption2).foregroundStyle(Color.zl.textMuted)
        }
    }
}
