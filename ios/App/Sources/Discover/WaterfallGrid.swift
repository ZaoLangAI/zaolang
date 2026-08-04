import SwiftUI

/// 双列瀑布墙：按封面真实宽高比，把下一张塞进当前更矮的那列（`04-screens.md` 发现页要求）。
/// Web 端用 CSS `columns-*` 自动排版，iOS 没有等价布局原语，这里手动按"等宽换算相对高度"
/// 贪心分配——两列足够简单，不需要引入完整的瀑布流依赖。
struct WaterfallGrid<Item: Identifiable, ItemContent: View>: View {
    let items: [Item]
    let aspectRatio: (Item) -> Double
    var spacing: CGFloat = 12
    @ViewBuilder let content: (Item) -> ItemContent

    var body: some View {
        let columns = distributed
        HStack(alignment: .top, spacing: spacing) {
            ForEach(0..<2, id: \.self) { columnIndex in
                VStack(spacing: spacing) {
                    ForEach(columns[columnIndex]) { item in
                        content(item)
                    }
                }
            }
        }
    }

    private var distributed: [[Item]] {
        var columnHeights = [Double](repeating: 0, count: 2)
        var columns: [[Item]] = [[], []]
        for item in items {
            let shorter = columnHeights[0] <= columnHeights[1] ? 0 : 1
            columns[shorter].append(item)
            let ratio = aspectRatio(item)
            columnHeights[shorter] += ratio > 0 ? 1 / ratio : 1
        }
        return columns
    }
}
